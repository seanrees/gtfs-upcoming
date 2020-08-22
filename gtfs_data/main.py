#!/usr/bin/env python3

import argparse
import collections
import logging
import sys
from typing import List

# Local imports
import database

def main(argv: List[str]) -> None:
  """Initialises the program."""

  parser = argparse.ArgumentParser(prog=argv[0])
  parser.add_argument('--gtfs', help='GTFS definitions', default='google_transit_combined')
  args = parser.parse_args()

  logging.basicConfig(
      format='%(asctime)s %(levelname)10s %(message)s',
      datefmt='%Y/%m/%d %H:%M:%S',
      level=logging.DEBUG)

  logging.info('Starting up...')

  logging.info('Loading GTFS data sources from "%s"...', args.gtfs)

  interesting_stops = ['8220DB002798', '8220DB000490', '8220DB000412']
  db = database.Database(args.gtfs, interesting_stops)
  db.Load()
  logging.info('Load complete.')

  for t in db.trip_db:
    arrival = ""
    sequence = ""
    for st in t.stop_times:
      if st['stop_id'] in interesting_stops:
        arrival = st['arrival_time']
        sequence = st['stop_sequence']
        break

    print(f"Trip id: {t.trip_id} : {t.trip_headsign} ({t.direction_id})")
    print(f"  Route: {t.route['route_short_name']} {t.route['route_long_name']}")
    print(f"  Stops: {len(t.stop_times)} (our stop is step {sequence} @ {arrival})")
    print()


if __name__ == '__main__':
  main(sys.argv)
