#!/usr/bin/env python3

import httpd
import nta
import gtfs_data.database
import transit

import argparse
import collections
import configparser
import datetime
import faulthandler
import functools
import json
import logging
import sys
import time
import urllib.request

from typing import List, NamedTuple


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
    stops = config['Upcoming']['InterestingStopIds'].split(',')

    return Configuration(
      api_key_primary=pri,
      api_key_secondary=sec,
      interesting_stops=stops)
  except KeyError as e:
    logging.critical('Required key missing in "%s": %s', filename, e)
    raise


class UpcomingJson:
  def __init__(self, transit: transit.Transit, stops: List[str]):
    self._transit = transit
    self._stops = stops

  def HandleRequest(self, req: httpd.RequestHandler) -> None:
    data = self._transit.GetUpcoming(self._stops)
    req.SendHeaders(200, 'application/json')
    req.Send(json.dumps({
      'current_timestamp': int(datetime.datetime.now().timestamp()),
      'upcoming': [d.Dict() for d in data]
    }))


def main(argv: List[str]) -> None:
  """Initialises the program."""

  parser = argparse.ArgumentParser(prog=argv[0])
  parser.add_argument('--config', help='Configuration file (INI file)', default='config.ini')
  parser.add_argument('--env', help='Use Prod or Test endpoints', default='test', choices=['prod', 'test'])
  parser.add_argument('--port', help='Port to run webserver on', default=6824)
  parser.add_argument('--gtfs', help='GTFS definitions', default='google_transit_combined')
  args = parser.parse_args()

  logging.basicConfig(
      format='%(asctime)s %(levelname)7s %(message)s',
      datefmt='%Y/%m/%d %H:%M:%S',
      level=logging.DEBUG)

  logging.info('Starting up')

  config = _read_config(args.config)
  if not config:
    exit(-1)

  logging.info('Loading GTFS data sources from "%s" for %d stops...',
    args.gtfs, len(config.interesting_stops))

  database = gtfs_data.database.Database(
    args.gtfs, config.interesting_stops)
  database.Load()
  logging.info('Load complete.')

  api_url = nta.TEST_URL
  if args.env == 'prod':
    api_url = nta.PROD_URL
  logging.info('API endpoint = %s (%s)', args.env, api_url)

  fetch_fn = functools.partial(nta.Fetch, config.api_key_primary, api_url)
  t = transit.Transit(fetch_fn, database)

  port = int(args.port)
  logging.info("Starting HTTP server on port %d", port)
  http = httpd.HTTPServer(port)
  http.Register('/upcoming.json', UpcomingJson(t, config.interesting_stops).HandleRequest)
  http.serve_forever()


if __name__ == '__main__':
  faulthandler.enable()
  main(sys.argv)
