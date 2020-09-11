import gtfs_data.loader

import logging
import os
from typing import AbstractSet, Any, List, Dict, NamedTuple

import prometheus_client    # type: ignore[import]


# Metrics
TRIPDB = prometheus_client.Summary(
  'tripdb_loaded_trips',
  'Trips loaded in the database')

TRIPDB_REQUESTS = prometheus_client.Counter(
  'tripdb_requests_total',
  'Requests to the Trip DB',
  ['found'])

STOPSDB = prometheus_client.Summary(
  'stopsdb_loaded_stops',
  'Stops loaded in the database')

STOPSDB_REQUESTS = prometheus_client.Counter(
  'stopsdb_requests_total',
  'Requests to the Stops DB',
  ['found'])

DATABASE_LOAD = prometheus_client.Summary(
  'database_load_seconds',
  'Time to load the database')


# From: https://developers.google.com/transit/gtfs/reference#routestxt
ROUTE_TYPES = {
  '0': 'TRAM',
  '1': 'SUBWAY',
  '2': 'RAIL',
  '3': 'BUS',
  '4': 'FERRY',
  '5': 'CABLE_TRAM',
  '6': 'AERIAL_LIFT',
  '7': 'FUNICULAR',
  '11': 'TROLLEYBUS',
  '12': 'MONORAIL'
}

class Trip(NamedTuple):
  trip_id: str
  trip_headsign: str
  direction_id: str
  route: Dict[str, str]
  stop_times: List[Dict[str, str]]


class Database:
  """Provides an easy-to-query interface for the GTFS database.

  This is not a generic API; this is tailored to the specific use-case of this
  application.
  """

  def __init__(self, data_dir: str, keep_stops: List[str]):
    """Initialises and loads the database.

    Args:
      data_dir: path to the GTFS data package
      keep_stops: a list of stops to filter the database data on. If keep_stops is empty,
        ALL stops are kept.
    """
    self._data_dir = data_dir
    self._keep_stops = keep_stops
    self._load_all_stops = len(keep_stops) == 0
    self._trip_db : Dict[str, Trip] = {}

  @DATABASE_LOAD.time()
  def Load(self):
    self._trip_db = self._LoadTripDB()
    TRIPDB.observe(len(self._trip_db.keys()))

    # If we need to constrain memory here at some point in future, we could
    # load just the stops listed in Trip.stop_times. There are ~10k stops now
    # so it didn't seem worthwhile to add the complexity.
    self._stops_db = self._Collect(self._Load('stops.txt'), 'stop_id')
    STOPSDB.observe(len(self._stops_db.keys()))

  def GetTrip(self, trip_id: str):
    ret = self._trip_db.get(trip_id, None)
    TRIPDB_REQUESTS.labels(ret is not None).inc()
    return ret

  def GetStop(self, stop_id: str) -> Dict[str,str]:
    ret = self._stops_db.get(stop_id, None)
    STOPSDB_REQUESTS.labels(ret is not None).inc()
    return ret

  def _LoadTripDB(self) -> Dict[str, Trip]:
    # First we need to extract the interesting trips and sequences.
    fltr = None
    if not self._load_all_stops:
      fltr = {'stop_id': set(self._keep_stops)}
    tmp_trips = self._Collect(self._Load('stop_times.txt', fltr),
      'trip_id',
      multi=True)

    # Now collect the Trip->List of stops
    stop_times = self._Collect(
      self._Load('stop_times.txt', {'trip_id': tmp_trips.keys()}),
      'trip_id',
      multi=True)

    # Lets load the routes.
    routes = self._Collect(self._Load('routes.txt'), 'route_id')

    # Now let's produce the trip database.
    trips = self._Collect(self._Load('trips.txt', {'trip_id': tmp_trips.keys()}),
      'trip_id')

    trip_db = {}
    for trip_id, row in trips.items():
      route_id = row['route_id']
      if route_id not in routes:
        logging.debug('Trip "%s" references unknown route_id "%s"', trip_id, route_id)

      st = stop_times.get(trip_id, None)
      if not st:
        logging.debug('Trip "%s" has no stop times', trip_id)

      t = Trip(trip_id, row['trip_headsign'], row['direction_id'],
               routes.get(route_id, None), st)
      trip_db[trip_id] = t

    return trip_db

  def _Load(self, filename: str, keep: Dict[str, AbstractSet[str]]=None):
    return gtfs_data.loader.Load(
      os.path.join(os.path.join(self._data_dir, filename)),
      keep)

  def _Collect(self, data: List[Dict[str, str]], key_name: str, multi: bool=False):
    ret : Dict[str, Any] = {}

    duplicates = 0

    for row in data:
      if key_name not in row:
        logging.error('Key "%s" not found in row %s', key_name, row)
        return None

      key = row[key_name]

      if multi:
        lst = ret.get(key, [])
        lst.append(row)
        ret[key] = lst
      else:
        if key in ret:
          duplicates += 1
        ret[key] = row

    if duplicates:
      logging.info('Detected %d duplicate %s keys', duplicates, key_name)

    return ret
