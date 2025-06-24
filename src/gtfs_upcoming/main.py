#!/usr/bin/env python3

import argparse
import configparser
import datetime
import faulthandler
import json
import logging
import os
import sys
from typing import NamedTuple

import prometheus_client  # type: ignore[import]
from opentelemetry import trace  # type: ignore[import]

from . import httpd, realtime, schedule, transit
from .__about__ import __version__
from .schedule import loader

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("tracer.transit")


# Metrics
API_ENV = prometheus_client.Info(
    'gtfs_api_environment',
    'Transit environment that gtfs-upcoming is bound')

BUILD_INFO = prometheus_client.Info(
    'gtfs_build_info',
    'Build info for the app')


class Configuration(NamedTuple):
    api_key_primary: str
    api_key_secondary: str
    interesting_stops: list[str]


def _read_config(filename: str) -> Configuration:
    logger.info('Reading "%s"', filename)

    config = configparser.ConfigParser()
    try:
        config.read(filename)
    except configparser.Error as e:
        logger.critical('Could not read "%s": %s', filename, e)
        raise

    try:
        # The NTA section was the original name. We keep it for compatibility.
        keys = config['NTA'] if config.has_section('NTA') else config['ApiKeys']
        primary_key = keys['PrimaryApiKey']
        secondary_key = keys['SecondaryApiKey']

        stops: list[str] = []
        stop_ids = config.get('Upcoming', 'InterestingStopIds', fallback=None)
        if stop_ids:
            stops = stop_ids.split(',')

        return Configuration(
            api_key_primary=primary_key,
            api_key_secondary=secondary_key,
            interesting_stops=stops)
    except KeyError as e:
        logger.critical('Required key missing in "%s": %s', filename, e)
        raise


class TransitHandler:
    def __init__(self, transit: transit.Transit, stops: list[str],
                 provider: str, env: str):
        self._transit = transit
        self._stops = stops
        self._provider = provider
        self._env = env

    def _add_tracing(self, fn):
        def wrapper(*args):
            current_span = trace.get_current_span()
            current_span.set_attributes({
                'gtfs-upcoming.provider': self._provider,
                'gtfs-upcoming.environment': self._env,
                'gtfs-upcoming.handler': fn.__name__,
                'gtfs-upcoming.app.version': __version__
            })
            return fn(*args)
        return wrapper

    @property
    def handle_upcoming(self):
        def handler(req: httpd.RequestHandler) -> None:
            stops = req.params.get('stop', self._stops)

            data = self._transit.get_upcoming(stops)
            req.send_headers(200, 'application/json')
            req.send(json.dumps({
                'current_timestamp': int(datetime.datetime.now().timestamp()),
                'upcoming': [d.dict() for d in data]
            }))
        return self._add_tracing(handler)

    @property
    def handle_scheduled(self):
        def handler(req: httpd.RequestHandler) -> None:
            stops = req.params.get('stop', self._stops)
            data = self._transit.get_scheduled(stops)

            req.send_headers(200, 'application/json')
            req.send(json.dumps({
                'current_timestamp': int(datetime.datetime.now().timestamp()),
                'scheduled': [d.dict() for d in data]
            }))
        return self._add_tracing(handler)

    @property
    def handle_live(self):
        def handler(req: httpd.RequestHandler) -> None:
            stops = req.params.get('stop', self._stops)
            data = self._transit.get_live(stops)

            req.send_headers(200, 'application/json')
            req.send(json.dumps({
                'current_timestamp': int(datetime.datetime.now().timestamp()),
                'live': [d.dict() for d in data]
            }))
        return self._add_tracing(handler)

    @property
    def handle_debug(self):
        def handler(req: httpd.RequestHandler) -> None:
            start = datetime.datetime.now()
            pb = self._transit.load_from_api()
            stop = datetime.datetime.now()

            req.send_headers(200, 'text/html')
            html = req.generate_html_head('Debug')
            html += f"<h1>Debug</h1><p>Interesting stops: {self._stops}</p>"
            html += (f"<pre>Received {pb.ByteSize() / 1024:.6} kB in "
                    f"{(stop - start).total_seconds():.6} seconds</pre>")
            html += f"<pre>{pb!s}</pre>"
            html += req.generate_html_foot()

            req.send(html)
        return self._add_tracing(handler)


def real_main(argv: list[str]) -> None:
    """Initialises the program."""

    parser = argparse.ArgumentParser(prog=argv[0])
    parser.add_argument('--config', help='Configuration file (INI file)',
                       default='config.ini')
    parser.add_argument('--env', help='Use Prod or Test endpoints',
                       default='test')
    parser.add_argument('--port', help='Port to run webserver on',
                       default=6824)
    parser.add_argument('--promport', help='Port to run Prometheus webserver on',
                       default=None)
    parser.add_argument('--gtfs', help='GTFS definitions',
                       default='google_transit_combined')
    parser.add_argument('--loader_max_threads', help='Max load threads',
                       default=os.cpu_count())
    parser.add_argument('--loader_max_rows_per_chunk',
                       help='Number of rows per threaded chunk',
                       default=100000)
    parser.add_argument('--loader_multiprocess_model',
                       help='Multiprocessing model to use',
                       choices=['thread', 'process'], default='thread')
    parser.add_argument('--provider',
                       help='One of nta (Ireland) or vicroads (Victoria Australia)',
                       default='nta')
    parser.add_argument('--log_level',
                       help='Logging level (DEBUG, INFO, WARNING, ERROR) '
                            '[default: %(default)s]',
                       default='INFO')

    args = parser.parse_args()

    try:
        level = getattr(logging, args.log_level)
    except AttributeError:
        print(f"Invalid --log_level: {args.log_level}")   # noqa: T201
        sys.exit(-1)

    logging.basicConfig(
        format='%(asctime)s [%(name)35s %(thread)d] %(levelname)10s %(message)s',
        datefmt='%Y/%m/%d %H:%M:%S',
        level=level)

    logger.info('Starting up gtfs-upcoming v%s', __version__)

    # We run Prometheus in a separate internal server. This is in case the main
    # serving webserver locks/crashes, we will retain metrics insight.
    if args.promport:
        prometheus_client.start_http_server(int(args.promport))

    API_ENV.info({
        'provider': args.provider,
        'env': args.env
    })

    BUILD_INFO.info({'version': __version__})

    config = _read_config(args.config)
    if not config:
        sys.exit(-1)

    loader.MaxThreads = int(args.loader_max_threads)
    loader.MaxRowsPerChunk = int(args.loader_max_rows_per_chunk)
    loader.MultiprocessModel = args.loader_multiprocess_model

    logger.info('Configured loader with %d threads, %d rows per chunk, '
                'parallelisation via %s',
                loader.MaxThreads, loader.MaxRowsPerChunk,
                loader.MultiprocessModel)

    logger.info('Loading GTFS data sources from "%s"', args.gtfs)
    if config.interesting_stops:
        logger.info('Restricting data sources to %d interesting stops',
                   len(config.interesting_stops))
    else:
        logger.info('Loading data for all stops.')

    try:
        database = schedule.Database(
            args.gtfs, config.interesting_stops)
        database.load()
        logger.info('Load complete.')
    except FileNotFoundError as fnfex:
        logger.error(fnfex)  # noqa: TRY400
        logger.fatal("Incomplete or missing GTFS database in %s. "
                    "Run update-database.sh", args.gtfs)
        sys.exit(-2)

    fetcher = realtime.make_fetcher(args.provider, args.env,
                                  config.api_key_primary)
    t = transit.Transit(fetcher.fetch, database)

    port = int(args.port)
    logger.info("Starting HTTP server on port %d", port)
    http = httpd.HTTPServer(port)
    handler = TransitHandler(t, config.interesting_stops, args.provider,
                            args.env)
    http.register('/upcoming.json', handler.handle_upcoming)
    http.register('/scheduled.json', handler.handle_scheduled)
    http.register('/live.json', handler.handle_live)
    http.register('/debugz', handler.handle_debug)
    http.serve_forever()


def main():
    faulthandler.enable()
    real_main(sys.argv)


if __name__ == '__main__':
    main()
