#!/usr/bin/env python3

import httpd
import nta
import gtfs_data.database
import gtfs_data.loader
import transit

import argparse
import collections
import configparser
import datetime
import faulthandler
import functools
import json
import logging
import os
import sys
import time
import urllib.request

from typing import List, NamedTuple

import prometheus_client    # type: ignore[import]


# Metrics
API_ENV = prometheus_client.Info(
  'gtfs_api_environment',
  'NTA environment that gtfs-upcoming is bound')


class Configuration(NamedTuple):
  api_key_primary: str
  api_key_secondary: str
  interesting_stops: List[str]


def _read_config(filename: str) -> Configuration:
  logging.info('Reading "%s"', filename)

  config = configparser.ConfigParser()
  try:
    config.read(filename)
  except configparser.Error as e:
    logging.critical('Could not read "%s": %s', filename, e)
    raise

  try:
    pri = config['NTA']['PrimaryApiKey']
    sec = config['NTA']['SecondaryApiKey']

    stops : List[str] = []
    stop_ids = config.get('Upcoming', 'InterestingStopIds', fallback=None)
    if stop_ids:
      stops = stop_ids.split(',')

    return Configuration(
      api_key_primary=pri,
      api_key_secondary=sec,
      interesting_stops=stops)
  except KeyError as e:
    logging.critical('Required key missing in "%s": %s', filename, e)
    raise


class TransitHandler:
  def __init__(self, transit: transit.Transit, stops: List[str]):
    self._transit = transit
    self._stops = stops

  def HandleUpcoming(self, req: httpd.RequestHandler) -> None:
    stops = req.params.get('stop', self._stops)

    data = self._transit.GetUpcoming(stops)
    req.SendHeaders(200, 'application/json')
    req.Send(json.dumps({
      'current_timestamp': int(datetime.datetime.now().timestamp()),
      'upcoming': [d.Dict() for d in data]
    }))

  def HandleScheduled(self, req: httpd.RequestHandler) -> None:
    stops = req.params.get('stop', self._stops)
    data = self._transit.GetScheduled(stops)

    req.SendHeaders(200, 'application/json')
    req.Send(json.dumps({
      'current_timestamp': int(datetime.datetime.now().timestamp()),
      'scheduled': [d.Dict() for d in data]
    }))

  def HandleLive(self, req: httpd.RequestHandler) -> None:
    stops = req.params.get('stop', self._stops)
    data = self._transit.GetLive(stops)

    req.SendHeaders(200, 'application/json')
    req.Send(json.dumps({
      'current_timestamp': int(datetime.datetime.now().timestamp()),
      'live': [d.Dict() for d in data]
    }))

  def HandleDebug(self, req: httpd.RequestHandler) -> None:
    start = datetime.datetime.now()
    pb = self._transit.LoadFromAPI()
    stop = datetime.datetime.now()

    req.SendHeaders(200, 'text/html')
    html = req.GenerateHTMLHead('Debug')
    html += f"<h1>Debug</h1><p>Interesting stops: {self._stops}</p>"
    html += f"<pre>Received {pb.ByteSize()/1024:.6} kB in {(stop-start).total_seconds():.6} seconds</pre>"
    html += f"<pre>{pb!s}</pre>"
    html += req.GenerateHTMLFoot()

    req.Send(html)


def main(argv: List[str]) -> None:
  """Initialises the program."""

  parser = argparse.ArgumentParser(prog=argv[0])
  parser.add_argument('--config', help='Configuration file (INI file)', default='config.ini')
  parser.add_argument('--env', help='Use Prod or Test endpoints', default='test', choices=['prod', 'test'])
  parser.add_argument('--port', help='Port to run webserver on', default=6824)
  parser.add_argument('--promport', help='Port to run Prometheus webserver on', default=None)
  parser.add_argument('--gtfs', help='GTFS definitions', default='google_transit_combined')
  parser.add_argument('--loader_max_threads', help='Max load threads', default=os.cpu_count())
  parser.add_argument('--loader_max_rows_per_chunk', help='Number of rows per threaded chunk', default=100000)
  args = parser.parse_args()

  logging.basicConfig(
      format='%(asctime)s %(levelname)7s %(message)s',
      datefmt='%Y/%m/%d %H:%M:%S',
      level=logging.DEBUG)

  logging.info('Starting up')

  # We run Prometheus in a separate internal server. This is in case the main
  # serving webserver locks/crashes, we will retain metrics insight.
  if args.promport:
    prometheus_client.start_http_server(int(args.promport))

  config = _read_config(args.config)
  if not config:
    exit(-1)

  gtfs_data.loader.MaxThreads = int(args.loader_max_threads)
  gtfs_data.loader.MaxRowsPerChunk = int(args.loader_max_rows_per_chunk)

  logging.info('Configured loader with %d threads, %d rows per chunk',
    gtfs_data.loader.MaxThreads, gtfs_data.loader.MaxRowsPerChunk)

  logging.info('Loading GTFS data sources from "%s"', args.gtfs)
  if config.interesting_stops:
    logging.info('Restricting data sources to %d interesting stops',
      len(config.interesting_stops))
  else:
    logging.info('Loading data for all stops.')

  database = gtfs_data.database.Database(
    args.gtfs, config.interesting_stops)
  database.Load()
  logging.info('Load complete.')

  api_url = nta.TEST_URL
  if args.env == 'prod':
    api_url = nta.PROD_URL
  API_ENV.info({'name': args.env, 'url': api_url})
  logging.info('API endpoint = %s (%s)', args.env, api_url)

  fetch_fn = functools.partial(nta.Fetch, config.api_key_primary, api_url)
  t = transit.Transit(fetch_fn, database)

  port = int(args.port)
  logging.info("Starting HTTP server on port %d", port)
  http = httpd.HTTPServer(port)
  handler = TransitHandler(t, config.interesting_stops)
  http.Register('/upcoming.json', handler.HandleUpcoming)
  http.Register('/scheduled.json', handler.HandleScheduled)
  http.Register('/live.json', handler.HandleLive)
  http.Register('/debugz', handler.HandleDebug)
  http.serve_forever()


if __name__ == '__main__':
  faulthandler.enable()
  main(sys.argv)
