import datetime
import logging
from collections.abc import Callable
from typing import Any, NamedTuple

import prometheus_client  # type: ignore[import]
from google.transit import gtfs_realtime_pb2  # type: ignore[import]
from opentelemetry import trace

from . import schedule

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


TRACE_PREFIX = 'gtfs-upcoming.transit.'

logger = logging.getLogger(__name__)

tracer = trace.get_tracer("tracer.transit")


def now() -> datetime.datetime:
  """Provides a convenient hook for mocking.

  datetime.datetime is native, so MagicMock can't monkeypatch it. This
  indirection provides a mocking point.
  """
  return datetime.datetime.now()


def parseTime(t: str) -> datetime.datetime:
  """Converts HH:MM:SS to a datetime.datetime"""
  base_date = now().date()

  hour, minutes, seconds = (int(x) for x in t.split(':', 3))
  if hour >= 24:
    base_date += datetime.timedelta(days=int(hour/24))
    hour %= 24

  return datetime.datetime.combine(base_date, datetime.time(hour, minutes, seconds))


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
  canceled: bool
  addedToSchedule: bool


  def Dict(self) -> dict[str,object]:
    """Wrap _asdict() so consumers don't need to know this is a namedtuple."""
    return self._asdict()

  @classmethod
  def FromTrip(cls, trip: schedule.Trip, stop_id: str, source: str, due: datetime.datetime, currentDateTime: datetime.datetime, canceled: bool, addedToSchedule: bool):   # noqa: FBT001
    return cls(
      trip_id=trip.trip_id,
      route=trip.route.short_name,
      route_type=schedule.ROUTE_TYPES[trip.route.route_type],
      headsign=trip.trip_headsign,
      direction=trip.direction_id,
      stop_id=stop_id,
      dueTime=due.time().strftime('%H:%M:%S'),
      dueInSeconds=delta_seconds(due, currentDateTime),
      source=source,
      canceled=canceled,
      addedToSchedule=addedToSchedule)


class Transit:
  def __init__(self, fetch_fn: Callable[[], bytes], db: schedule.Database):
    self._fetch_fn = fetch_fn
    self._database = db

  @tracer.start_as_current_span("LoadFromAPI")
  def LoadFromAPI(self) -> gtfs_realtime_pb2.FeedMessage:
    raw = self._fetch_fn()
    ret = gtfs_realtime_pb2.FeedMessage()
    ret.ParseFromString(raw)
    return ret

  def _BuildTripFromUpdate(self, tu: gtfs_realtime_pb2.TripUpdate, interesting_stops: list[str]) -> schedule.database.Trip:
    trip_id = tu.trip.trip_id

    route = self._database.GetRoute(tu.trip.route_id)
    if route:
      stop_times : list[dict[str, Any]] = []

      for stu in tu.stop_time_update:
        if stu.stop_id in interesting_stops:
          time = None
          if stu.HasField('arrival') and stu.arrival.HasField('time'):
            time = stu.arrival.time

          if stu.HasField('departure') and stu.departure.HasField('time'):
            time = stu.departure.time

          if not time:
            logger.warning("ADDED trip %s, stop_id %s, has no arrival or departure time (ignoring it)", trip_id, stu.stop_id)
            continue

          logging.debug("ADDED trip %s has an interesting stop at %s, creating a Trip", trip_id, stu.stop_id)
          stop_times.append({
            'trip_id': trip_id,
            'stop_id': stu.stop_id,
            'stop_sequence': stu.stop_sequence,
            'arrival_time': datetime.datetime.fromtimestamp(time).strftime("%H:%M:%S"),
            'departure_time': datetime.datetime.fromtimestamp(time).strftime("%H:%M:%S"),
          })

      if stop_times:
        return schedule.database.Trip(
          trip_id, route.inferred_headsign, route.inferred_direction_id, route.inferred_service_id,
          route, stop_times)

      logger.debug("ADDED trip %s matches a route but does not reference any interesting stops", trip_id)

    logger.debug("ADDED trip %s either has no interesting stops or does not match a known route, skipping", trip_id)
    return None

  @SCHEDULED_TIME.time()
  @tracer.start_as_current_span("GetScheduled")
  def GetScheduled(self, interesting_stops: list[str]) -> list[Upcoming]:
    start = now()
    end = now() + datetime.timedelta(minutes=120)

    ret : list[Upcoming] = []

    for stop_id in interesting_stops:
      trips = self._database.GetScheduledFor(stop_id, start, end)

      for t in trips:
        due = ''

        for s in t.stop_times:
          if s['stop_id'] == stop_id:
            due = parseTime(s['arrival_time'])
            break

        ret.append(Upcoming.FromTrip(t, stop_id, 'SCHEDULE', due, now(), canceled=False, addedToSchedule=False))

    SCHEDULED_RETURNED.observe(len(ret))
    trace.get_current_span().set_attribute(TRACE_PREFIX + 'scheduled', len(ret))

    return sorted(ret, key=lambda x: x.dueInSeconds)

  @LIVE_TIME.time()
  @tracer.start_as_current_span("GetLive")
  def GetLive(self, interesting_stops: list[str]) -> list[Upcoming]:
    resp = self.LoadFromAPI()
    ret = []
    early = 0
    delayed = 0
    ontime = 0
    notUpdate = 0
    unexpectedScheduleRelationship = 0
    tripsAdded = 0
    tripsCanceled = 0

    current = now()

    for e in resp.entity:
      if not e.HasField('trip_update'):
        notUpdate += 1
        continue

      trip_update = e.trip_update
      trip = trip_update.trip

      scheduled = trip.schedule_relationship == gtfs_realtime_pb2.TripDescriptor.SCHEDULED
      canceled = trip.schedule_relationship == gtfs_realtime_pb2.TripDescriptor.CANCELED
      added = trip.schedule_relationship == gtfs_realtime_pb2.TripDescriptor.ADDED

      trip_from_db = self._database.GetTrip(trip.trip_id)
      if not trip_from_db and added:
          trip_from_db = self._BuildTripFromUpdate(trip_update, interesting_stops)

      if not trip_from_db:
          continue

      if not (scheduled or canceled or added):
        sr = gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship.Name(trip.schedule_relationship)
        logger.warning('received unexpected schedule_relationship for trip_id %s: %s', trip.trip_id, sr)
        unexpectedScheduleRelationship += 1
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
      if scheduled:
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

      if canceled:
        tripsCanceled += 1

      if added:
        tripsAdded += 1

      ret.append(Upcoming.FromTrip(trip_from_db, stop_id, 'LIVE', updated_arrival_time, current, canceled=canceled, addedToSchedule=added))


    MATCHED_TRIPS.labels('ontime').observe(ontime)
    MATCHED_TRIPS.labels('early').observe(early)
    MATCHED_TRIPS.labels('delayed').observe(delayed)
    ENTITIES_IGNORED.labels('wrong_type').observe(notUpdate)
    ENTITIES_IGNORED.labels('not_scheduled').observe(unexpectedScheduleRelationship)
    ENTITIES_RETURNED.observe(len(resp.entity))

    trace.get_current_span().set_attributes({
      TRACE_PREFIX + 'matched-ontime': ontime,
      TRACE_PREFIX + 'matched-early': early,
      TRACE_PREFIX + 'matched-delayed': delayed,
      TRACE_PREFIX + 'matched-canceled': tripsCanceled,
      TRACE_PREFIX + 'ignored-wrong_type': notUpdate,
      TRACE_PREFIX + 'ignored-unexpected_schedule_relationship': unexpectedScheduleRelationship,
      TRACE_PREFIX + 'ignored-added': tripsAdded,
      TRACE_PREFIX + 'entities-returned': len(resp.entity),
    })

    return ret

  @UPCOMING_TIME.time()
  @tracer.start_as_current_span("GetUpcoming")
  def GetUpcoming(self, interesting_stops: list[str]) -> list[Upcoming]:
    ret : list[Upcoming] = []

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
    trace.get_current_span().set_attribute(TRACE_PREFIX + 'matched-live', known_count)

    # Remove canceled trips, sort ascending by dueInSeconds.
    return sorted(filter(lambda t: not t.canceled, ret), key=lambda x: x.dueInSeconds)
