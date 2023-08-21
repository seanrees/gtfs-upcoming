import gtfs_data.database

import datetime
import logging
from typing import Any, Callable, Dict, List, NamedTuple

from google.transit import gtfs_realtime_pb2    # type: ignore[import]
import prometheus_client                        # type: ignore[import]

# Metrics
MATCHED_TRIPS = prometheus_client.Summary(
  'gtfs_interesting_trips',
  'Trips returned matching configured InterestingStops',
  ['state'])

ENTITIES_RETURNED = prometheus_client.Summary(
  'gtfs_returned_entities',
  'Entities returned from API')

ENTITIES_IGNORED = prometheus_client.Summary(
  'gtfs_ignored_entities',
  'Entities ignored in API, because they were not TripUpdates or not Scheduled',
  ['reason'])

SCHEDULED_RETURNED = prometheus_client.Summary(
  'gtfs_transit_scheduled_trips_returned',
  'Number of scheduled trips returned'
)

SCHEDULED_AND_LIVE = prometheus_client.Summary(
  'gtfs_transit_scheduled_trips_matching_live',
  'Number of scheduled trips returned that are also in the live feed'
)

UPCOMING_TIME = prometheus_client.Summary(
  'gtfs_transit_getupcoming_run_seconds',
  'Time to run GetUpcoming')

SCHEDULED_TIME = prometheus_client.Summary(
  'gtfs_transit_getscheduled_run_seconds',
  'Time to run GetScheduled')

LIVE_TIME = prometheus_client.Summary(
  'gtfs_transit_getlive_run_seconds',
  'Time to run GetLive')


def now() -> datetime.datetime:
  """Provides a convenient hook for mocking.

  datetime.datetime is native, so MagicMock can't monkeypatch it. This
  indirection provides a mocking point.
  """
  return datetime.datetime.now()


def parseTime(t: str) -> datetime.datetime:
  """Converts HH:MM:SS to a datetime.datetime"""
  base_date = now().date()
  if t.startswith('24:'):
    t = t.replace('24:', '00:')
    base_date += datetime.timedelta(days=1)
  return datetime.datetime.combine(base_date, datetime.datetime.strptime(t, '%H:%M:%S').time())


def delta_seconds(now: datetime.datetime, then: datetime.datetime) -> float:
  """Returns time in seconds between two datetime.times"""
  return (now - then).total_seconds()


class Upcoming(NamedTuple):
  trip_id: str
  route: str
  route_type: str
  headsign: str
  direction: str
  stop_id: str
  dueTime: str
  dueInSeconds: float
  source: str


  def Dict(self) -> Dict[str,Any]:
    """Wrap _asdict() so consumers don't need to know this is a namedtuple."""
    return self._asdict()

  @classmethod
  def FromTrip(cls, trip: gtfs_data.database.Trip, stop_id: str, source: str, due: str, currentDateTime: datetime.datetime):
    return cls(
      trip_id=trip.trip_id,
      route=trip.route['route_short_name'],
      route_type=gtfs_data.database.ROUTE_TYPES[trip.route['route_type']],
      headsign=trip.trip_headsign,
      direction=trip.direction_id,
      stop_id=stop_id,
      dueTime=due,
      dueInSeconds=delta_seconds(parseTime(due), currentDateTime),
      source=source)


class Transit:
  def __init__(self, fetch_fn: Callable[[], bytes], db: gtfs_data.database.Database):
    self._fetch_fn = fetch_fn
    self._database = db

  def LoadFromAPI(self) -> gtfs_realtime_pb2.FeedMessage:
    raw = self._fetch_fn()
    ret = gtfs_realtime_pb2.FeedMessage()
    ret.ParseFromString(raw)
    return ret

  @SCHEDULED_TIME.time()
  def GetScheduled(self, interesting_stops: List[str]) -> List[Upcoming]:
    start = now()
    end = now() + datetime.timedelta(minutes=120)

    ret : List[Upcoming] = []

    for stop_id in interesting_stops:
      trips = self._database.GetScheduledFor(stop_id, start, end)

      for t in trips:
        due = ''

        for s in t.stop_times:
          if s['stop_id'] == stop_id:
            due = s['arrival_time']
            break

        ret.append(Upcoming.FromTrip(t, stop_id, 'SCHEDULE', due, now()))

    SCHEDULED_RETURNED.observe(len(ret))

    return sorted(ret, key=lambda x: x.dueInSeconds)

  @LIVE_TIME.time()
  def GetLive(self, interesting_stops: List[str]) -> List[Upcoming]:
    resp = self.LoadFromAPI()
    ret = []
    early = 0
    delayed = 0
    ontime = 0
    notUpdate = 0
    notScheduled = 0

    current = now()

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
              # parses POSIX timestamp into datetime
              # (https://developers.google.com/transit/gtfs-realtime/reference#message-feedentity)
              updated_arrival_time = datetime.datetime.fromtimestamp(
                stu.arrival.time)
        else:
            # We don't need to read anything past our stop.
            break

      if current > updated_arrival_time:
        continue

      if updated_arrival_time < arrival_time:
        early += 1
      elif updated_arrival_time == arrival_time:
        ontime += 1
      else:
        delayed += 1

      due = updated_arrival_time.strftime("%H:%M:%S")
      ret.append(Upcoming.FromTrip(trip_from_db, stop_id, 'LIVE', due, current))

    MATCHED_TRIPS.labels('ontime').observe(ontime)
    MATCHED_TRIPS.labels('early').observe(early)
    MATCHED_TRIPS.labels('delayed').observe(delayed)
    ENTITIES_IGNORED.labels('wrong_type').observe(notUpdate)
    ENTITIES_IGNORED.labels('not_scheduled').observe(notScheduled)
    ENTITIES_RETURNED.observe(len(resp.entity))

    return ret

  @UPCOMING_TIME.time()
  def GetUpcoming(self, interesting_stops: List[str]) -> List[Upcoming]:
    ret : List[Upcoming] = []

    scheduled = self.GetScheduled(interesting_stops)
    known_trips = {s.trip_id: s for s in scheduled}
    known_count = 0

    ret = self.GetLive(interesting_stops)
    for t in ret:
      if t.trip_id in known_trips:
        del known_trips[t.trip_id]
        known_count += 1

    for v in known_trips.values():
      ret.append(v)

    SCHEDULED_AND_LIVE.observe(known_count)

    return sorted(ret, key=lambda x: x.dueInSeconds)
