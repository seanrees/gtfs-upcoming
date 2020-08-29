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
  'Trips returned matching configured InterestingStops')

DELAYED_TRIPS = prometheus_client.Summary(
  'interesting_delayed_trips',
  'Trips for InterestingStops that ran late')

ENTITIES_RETURNED = prometheus_client.Summary(
  'gtfs_returned_entities',
  'Entities returned from API')

ENTITIES_IGNORED = prometheus_client.Summary(
  'gtfs_ignored_entities',
  'Entities ignored in API, because they were not TripUpdates')


class Upcoming(NamedTuple):
  route: str
  route_type: str
  headsign: str
  destination: str
  direction: str
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

def delta_seconds(now: datetime.time, then: datetime.time) -> float:
  """Returns time in seconds between two datetime.times"""
  td = lambda t : datetime.timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)
  return (td(now) - td(then)).total_seconds()


class Transit:
  def __init__(self, fetch_fn: Callable[[], bytes], db: gtfs_data.database.Database):
    self._fetch_fn = fetch_fn
    self._database = db

  def _LoadFromAPI(self) -> gtfs_realtime_pb2.FeedMessage:
    raw = self._fetch_fn()
    ret = gtfs_realtime_pb2.FeedMessage()
    ret.ParseFromString(raw)
    return ret

  def GetUpcoming(self, interesting_stops: List[str]) -> List[Upcoming]:
    resp = self._LoadFromAPI()
    ret = []
    delayed = 0
    ignored = 0

    ENTITIES_RETURNED.observe(len(resp.entity))

    for e in resp.entity:
      if not e.HasField('trip_update'):
        logging.info('API response has no trip_update, bailing')
        ignored += 1
        continue

      trip_update = e.trip_update
      trip = trip_update.trip

      if trip.schedule_relationship != gtfs_realtime_pb2.TripDescriptor.SCHEDULED:
        continue

      trip_from_db = self._database.GetTrip(trip.trip_id)
      if not trip_from_db:
        continue

      sequence = -1
      arrival_time = ""
      for st in trip_from_db.stop_times:
        if st['stop_id'] in interesting_stops:
          sequence = int(st['stop_sequence'])
          arrival_time = st['arrival_time']
          break

      delay = None
      updated_arrival_time = None
      for stu in trip_update.stop_time_update:
        if int(stu.stop_sequence) <= sequence:
          if stu.HasField('arrival'):
            delay = None
            updated_arrival_time = None

            if stu.arrival.HasField('delay'):
              delay = stu.arrival.delay
            if stu.arrival.HasField('time'):
              updated_arrival_time = stu.arrival.time
        else:
            # We don't need to read anything past our stop.
            break

      destination = self._database.GetStop(
        trip_from_db.stop_times[-1]['stop_id']).get('stop_name', '')

      is_delayed = False
      arrival_dt = datetime.datetime.strptime(arrival_time, '%H:%M:%S')
      if updated_arrival_time:
        arrival_dt = datetime.datetime.fromtimestamp(updated_arrival_time)
        is_delayed = True
      elif delay:
        arrival_dt += datetime.timedelta(seconds=int(delay))
        is_delayed = True

      arrival = arrival_dt.time()
      current = now()
      if arrival < current.time():
        continue

      # Only include delays at this point; we may have excluded trips immediately
      # above if they had already passed our stop.
      if is_delayed:
        delayed += 1

      route = trip_from_db.route['route_short_name']
      route_type = gtfs_data.database.ROUTE_TYPES[trip_from_db.route['route_type']]
      ret.append(Upcoming(
        route=route,
        route_type=route_type,
        headsign=trip_from_db.trip_headsign,
        destination=destination,
        direction=trip_from_db.direction_id,
        dueTime=arrival.strftime("%H:%M:%S"),
        dueInSeconds=delta_seconds(arrival, current.time())))


    ENTITIES_IGNORED.observe(ignored)
    MATCHED_TRIPS.observe(len(ret))
    DELAYED_TRIPS.observe(delayed)
    return ret
