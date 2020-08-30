import gtfs_data.database

import aapipfix
import datetime
import logging
from typing import Any, Callable, Dict, List, NamedTuple

from google.transit import gtfs_realtime_pb2    # type: ignore[import]
import prometheus_client                        # type: ignore[import]

# Metrics
MATCHED_TRIPS = prometheus_client.Summary(
  'interesting_trips',
  'Trips returned matching configured InterestingStops',
  ['state'])

ENTITIES_RETURNED = prometheus_client.Summary(
  'gtfs_returned_entities',
  'Entities returned from API')

ENTITIES_IGNORED = prometheus_client.Summary(
  'gtfs_ignored_entities',
  'Entities ignored in API, because they were not TripUpdates or not Scheduled',
  ['reason'])


class Upcoming(NamedTuple):
  route: str
  route_type: str
  headsign: str
  direction: str
  stop_id: str
  dueTime: str
  dueInSeconds: float

  def Dict(self) -> Dict[str,Any]:
    """Wrap _asdict() so consumers don't need to know this is a namedtuple."""
    return self._asdict()


def now() -> datetime.datetime:
  """Provides a convenient hook for mocking.

  datetime.datetime is native, so MagicMock can't monkeypatch it. This
  indirection provides a mocking point.
  """
  return datetime.datetime.now()


def parseTime(t: str) -> datetime.datetime:
  """Converts HH:MM:SS to a datetime.datetime"""
  return datetime.datetime.strptime(t, '%H:%M:%S')


def delta_seconds(now: datetime.time, then: datetime.time) -> float:
  """Returns time in seconds between two datetime.times"""
  td = lambda t : datetime.timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)
  return (td(now) - td(then)).total_seconds()


class Transit:
  def __init__(self, fetch_fn: Callable[[], bytes], db: gtfs_data.database.Database):
    self._fetch_fn = fetch_fn
    self._database = db

  def LoadFromAPI(self) -> gtfs_realtime_pb2.FeedMessage:
    raw = self._fetch_fn()
    ret = gtfs_realtime_pb2.FeedMessage()
    ret.ParseFromString(raw)
    return ret

  def GetUpcoming(self, interesting_stops: List[str]) -> List[Upcoming]:
    resp = self.LoadFromAPI()
    ret = []
    early = 0
    delayed = 0
    ontime = 0
    notUpdate = 0
    notScheduled = 0

    current = now().time()

    for e in resp.entity:
      if not e.HasField('trip_update'):
        notUpdate += 1
        continue

      trip_update = e.trip_update
      trip = trip_update.trip

      if trip.schedule_relationship != gtfs_realtime_pb2.TripDescriptor.SCHEDULED:
        notScheduled += 1
        continue

      trip_from_db = self._database.GetTrip(trip.trip_id)
      if not trip_from_db:
        continue

      sequence = -1
      arrival_time = datetime.datetime.fromtimestamp(1)
      stop_id = ""
      for st in trip_from_db.stop_times:
        if st['stop_id'] in interesting_stops:
          stop_id = st['stop_id']
          sequence = int(st['stop_sequence'])
          arrival_time = parseTime(st['arrival_time'])
          break

      updated_arrival_time = arrival_time
      for stu in trip_update.stop_time_update:
        if int(stu.stop_sequence) <= sequence:
          if stu.HasField('arrival'):
            if stu.arrival.HasField('delay'):
              secs = int(stu.arrival.delay)
              updated_arrival_time += datetime.timedelta(seconds=secs)
            if stu.arrival.HasField('time'):
              updated_arrival_time = parseTime(stu.arrival.time)
        else:
            # We don't need to read anything past our stop.
            break

      if current > updated_arrival_time.time():
        continue

      if updated_arrival_time < arrival_time:
        early += 1
      elif updated_arrival_time == arrival_time:
        ontime += 1
      else:
        delayed += 1

      route = trip_from_db.route['route_short_name']
      route_type = gtfs_data.database.ROUTE_TYPES[trip_from_db.route['route_type']]
      ret.append(Upcoming(
        route=route,
        route_type=route_type,
        headsign=trip_from_db.trip_headsign,
        direction=trip_from_db.direction_id,
        stop_id=stop_id,
        dueTime=updated_arrival_time.strftime("%H:%M:%S"),
        dueInSeconds=delta_seconds(updated_arrival_time.time(), current)))


    MATCHED_TRIPS.labels('ontime').observe(ontime)
    MATCHED_TRIPS.labels('early').observe(early)
    MATCHED_TRIPS.labels('delayed').observe(delayed)
    ENTITIES_IGNORED.labels('wrong_type').observe(notUpdate)
    ENTITIES_IGNORED.labels('not_scheduled').observe(notScheduled)
    ENTITIES_RETURNED.observe(len(resp.entity))

    return ret
