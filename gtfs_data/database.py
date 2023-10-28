import gtfs_data.loader

import collections
import datetime
import logging
import os
from typing import AbstractSet, Any, List, Dict, NamedTuple

import prometheus_client    # type: ignore[import]


# Metrics
TRIPDB = prometheus_client.Summary(
  'gtfs_tripdb_loaded_trips',
  'Trips loaded in the database')

TRIPDB_REQUESTS = prometheus_client.Counter(
  'gtfs_tripdb_requests_total',
  'Requests to the Trip DB',
  ['found'])

DATABASE_LOAD = prometheus_client.Summary(
  'gtfs_database_load_seconds',
  'Time to load the database')

SCHEDULE_RESPONSE  = prometheus_client.Summary(
  'gtfs_schedule_returned_trips',
  'Response sizes for GetSchedule()')

# From: https://developers.google.com/transit/gtfs/reference
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

CALENDAR_DAYS = [
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
  'sunday',
]

CALENDAR_SERVICE_NOT_AVAILABLE = "0"

CALENDAR_EXCEPTION_SERVICE_ADDED = "1"
CALENDAR_EXCEPTION_SERVICE_REMOVED = "2"


class Trip(NamedTuple):
  trip_id: str
  trip_headsign: str
  direction_id: str
  service_id: str
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
    self._stops_db : Dict[str, List[Dict[str, str]]] = {}
    self._trip_db : Dict[str, Trip] = {}
    self._calendar_db : Dict[str, Dict[str, str]] = {}
    self._exceptions_db : Dict[str, Dict[datetime.date, str]] = {}

  @DATABASE_LOAD.time()
  def Load(self):
    self._stops_db = self._LoadStops()
    self._trip_db = self._LoadTrips()
    self._calendar_db = self._LoadCalendar()
    self._exceptions_db = self._LoadExceptions()

    TRIPDB.observe(len(self._trip_db.keys()))

  def GetTrip(self, trip_id: str):
    ret = self._trip_db.get(trip_id, None)
    TRIPDB_REQUESTS.labels(ret is not None).inc()
    return ret

  def _IsValidServiceDay(self, dt: datetime.date, trip_id: str) -> bool:
    trip = self.GetTrip(trip_id)
    day = CALENDAR_DAYS[dt.weekday()]

    trip = self.GetTrip(trip_id)
    service = self._calendar_db.get(trip.service_id, None)
    if not service:
      logging.error('service "%s" not found in database', trip.service_id)
      return False

    start = service['start_date']
    end = service['end_date']
    if dt < start or dt > end:
      return False
    
    exc = self._exceptions_db.get(trip.service_id, {}).get(dt)
    if service.get(day) == CALENDAR_SERVICE_NOT_AVAILABLE:
      return exc == CALENDAR_EXCEPTION_SERVICE_ADDED

    return exc != CALENDAR_EXCEPTION_SERVICE_REMOVED

  def GetScheduledFor(self, stop_id: str, start: datetime.datetime, end: datetime.datetime):
    """Returns the trips that are scheduled to stop at stop_id between start and end.

    Args:
      stop_id: stop id to look trips up for
      start: only return trips after this time
      end: only return trips that arrive before this time

    Return:
      List[Trip]
    """
    ret : List[Trip] = []

    stops = self._stops_db.get(stop_id, None)
    if not stops:
      logging.error('stop "%s" not found in database', stop_id)
      return ret

    if end < start:
      raise ValueError('start must come before end')

    one_day = datetime.timedelta(days=1)
    start_service_date = start.date()-one_day
    end_service_date = end.date()

    possibility = collections.namedtuple('possibility', ['service_date', 'arrival_time'])

    for s in stops:
      trip_id = s['trip_id']
      arrival_time_str = s['arrival_time']

      try:
        # GTFS's data format allows for hours >24 to indicate times the
        # next day. E.g; 25:00 = 0100+1; this is useful if a service starts
        # on one day and carries through to the next.
        hour, minute, second = [int(x) for x in arrival_time_str.split(':')]
        delta = datetime.timedelta(days=0)

        if hour >= 24:
          delta = one_day
          hour -= 24

        a = datetime.time(hour=hour, minute=minute, second=second)

        possibles : List[possibility] = []
        service_date = start_service_date
        while service_date <= end_service_date:
          arrival_time = datetime.datetime.combine(service_date, a)+delta
          possibles.append(possibility(service_date, arrival_time))

          service_date += one_day
      except ValueError:
        logging.exception('invalid format for arrival_time_str "%s"',
          arrival_time_str)
        continue

      for p in possibles:
        valid_day = self._IsValidServiceDay(p.service_date, trip_id)
        if valid_day and p.arrival_time >= start and p.arrival_time <= end:
          ret.append(self.GetTrip(trip_id))

    SCHEDULE_RESPONSE.observe(len(ret))

    return ret

  def _LoadStops(self) -> Dict[str, Dict[str, str]]:
    # First we need to extract the interesting trips and sequences.
    if self._load_all_stops:
      tmp_stop_times = self._Load('stop_times.txt')
    else:
      tmp_stop_times = self._Load('stop_times.txt',
        {'stop_id': set(self._keep_stops)})

    return self._Collect(tmp_stop_times, 'stop_id', multi=True)

  def _LoadTrips(self) -> Dict[str, Trip]:
    trip_ids = set()
    for vals in self._stops_db.values():
      for stop in vals:
        trip_ids.add(stop['trip_id'])

    # Now collect the Trip->List of stops
    stop_times = self._Collect(
      self._Load('stop_times.txt', {'trip_id': trip_ids}),
      'trip_id',
      multi=True)

    # Lets load the routes.
    routes = self._Collect(self._Load('routes.txt'), 'route_id')

    # Now let's produce the trip database.
    trips = self._Collect(self._Load('trips.txt', {'trip_id': trip_ids}),
      'trip_id')

    trip_db = {}
    for trip_id, row in trips.items():
      route_id = row['route_id']
      if route_id not in routes:
        logging.debug('Trip "%s" references unknown route_id "%s"', trip_id, route_id)

      st = stop_times.get(trip_id, None)
      if not st:
        logging.debug('Trip "%s" has no stop times', trip_id)

      t = Trip(trip_id, row['trip_headsign'], row['direction_id'], row['service_id'],
               routes.get(route_id, None), st)
      trip_db[trip_id] = t

    return trip_db

  def _LoadCalendar(self) -> Dict[str, Dict[str, str]]:
    """Loads calendar.txt."""
    dates = self._Collect(self._Load('calendar.txt'), 'service_id')

    for _, data in dates.items():
      start = datetime.datetime.strptime(data['start_date'], '%Y%m%d').date()
      end = datetime.datetime.strptime(data['end_date'], '%Y%m%d').date()
      data['start_date'] = start
      data['end_date'] = end
    
    return dates

  def _LoadExceptions(self) -> Dict[str, Dict[datetime.date, str]]:
    """Loads calendar_dates.txt and preparses dates for easy lookup."""
    dates = self._Collect(self._Load('calendar_dates.txt'), 'service_id', multi=True)
    ret : Dict[str, Dict] = {service_id: {} for service_id in dates}

    for service_id, data in dates.items():
      for d in data:
        dt = datetime.datetime.strptime(d['date'], '%Y%m%d').date()
        ret[service_id][dt] = d['exception_type']

    return ret

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
