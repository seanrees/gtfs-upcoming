#!/usr/bin/env python3

import nta
import gtfs_data.database
import transit

import argparse
import collections
import configparser
import functools
import logging
import site
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


def main(argv: List[str]) -> None:
  """Initialises the program."""

  parser = argparse.ArgumentParser(prog=argv[0])
  parser.add_argument('--config', help='Configuration file (INI file)', default='config.ini')
  parser.add_argument('--env', help='Use Prod or Test endpoints', default='test', choices=['prod', 'test'])
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

  while True:
    up = t.GetUpcoming(config.interesting_stops)

    for u in up:
      print(u)

    print()

    try:
      time.sleep(30)
    except KeyboardInterrupt:
      break


if __name__ == '__main__':
  main(sys.argv)
