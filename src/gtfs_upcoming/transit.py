from __future__ import annotations

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


def parse_time(time_str: str) -> datetime.datetime:
    """Converts HH:MM:SS to a datetime.datetime"""
    base_date = now().date()

    hour, minutes, seconds = (int(x) for x in time_str.split(':', 3))
    if hour >= 24:
        base_date += datetime.timedelta(days=int(hour / 24))
        hour %= 24

    return datetime.datetime.combine(base_date,
                                    datetime.time(hour, minutes, seconds))


def delta_seconds(now_time: datetime.datetime, then: datetime.datetime) -> float:
    """Returns time in seconds between two datetime.times"""
    return (now_time - then).total_seconds()


class Upcoming(NamedTuple):
    trip_id: str
    route: str
    route_type: str
    headsign: str
    direction: str
    stop_id: str
    due_time: str
    due_in_seconds: float
    source: str
    canceled: bool
    added_to_schedule: bool

    def dict(self) -> dict[str, object]:
        """Wrap _asdict() so consumers don't need to know this is a namedtuple."""
        return self._asdict()

    @classmethod
    def from_trip(cls, trip: schedule.Trip, stop_id: str, source: str,
                  due: datetime.datetime, current_datetime: datetime.datetime,
                  canceled: bool, added_to_schedule: bool):   # noqa: FBT001
        return cls(
            trip_id=trip.trip_id,
            route=trip.route.short_name,
            route_type=schedule.ROUTE_TYPES[trip.route.route_type],
            headsign=trip.trip_headsign,
            direction=trip.direction_id,
            stop_id=stop_id,
            due_time=due.time().strftime('%H:%M:%S'),
            due_in_seconds=delta_seconds(due, current_datetime),
            source=source,
            canceled=canceled,
            added_to_schedule=added_to_schedule)


class Transit:
    def __init__(self, fetch_fn: Callable[[], bytes], db: schedule.Database):
        self._fetch_fn = fetch_fn
        self._database = db

    @tracer.start_as_current_span("LoadFromAPI")
    def load_from_api(self) -> gtfs_realtime_pb2.FeedMessage:
        raw = self._fetch_fn()
        ret = gtfs_realtime_pb2.FeedMessage()
        ret.ParseFromString(raw)
        return ret

    def _build_trip_from_update(self, tu: gtfs_realtime_pb2.TripUpdate,
                               interesting_stops: list[str]) -> schedule.database.Trip | None:
        trip_id = tu.trip.trip_id

        route = self._database.get_route(tu.trip.route_id)
        if route:
            stop_times: list[dict[str, Any]] = []

            for stu in tu.stop_time_update:
                if stu.stop_id in interesting_stops:
                    time = None
                    if stu.HasField('arrival') and stu.arrival.HasField('time'):
                        time = stu.arrival.time

                    if stu.HasField('departure') and stu.departure.HasField('time'):
                        time = stu.departure.time

                    if not time:
                        logger.warning("ADDED trip %s, stop_id %s, has no arrival or "
                                     "departure time (ignoring it)", trip_id, stu.stop_id)
                        continue

                    logging.debug("ADDED trip %s has an interesting stop at %s, "
                                "creating a Trip", trip_id, stu.stop_id)
                    stop_times.append({
                        'trip_id': trip_id,
                        'stop_id': stu.stop_id,
                        'stop_sequence': stu.stop_sequence,
                        'arrival_time': datetime.datetime.fromtimestamp(time).strftime("%H:%M:%S"),
                        'departure_time': datetime.datetime.fromtimestamp(time).strftime("%H:%M:%S"),
                    })

            if stop_times:
                return schedule.database.Trip(
                    trip_id, route.inferred_headsign, route.inferred_direction_id,
                    route.inferred_service_id,
                    route, stop_times)

            logger.debug("ADDED trip %s matches a route but does not reference "
                        "any interesting stops", trip_id)

        logger.debug("ADDED trip %s either has no interesting stops or does not "
                    "match a known route, skipping", trip_id)
        return None

    @SCHEDULED_TIME.time()
    @tracer.start_as_current_span("GetScheduled")
    def get_scheduled(self, interesting_stops: list[str]) -> list[Upcoming]:
        start = now()
        end = now() + datetime.timedelta(minutes=120)

        ret: list[Upcoming] = []

        for stop_id in interesting_stops:
            trips = self._database.get_scheduled_for(stop_id, start, end)

            for trip in trips:
                due = None

                for stop_time in trip.stop_times:
                    if stop_time['stop_id'] == stop_id:
                        due = parse_time(stop_time['arrival_time'])
                        break

                if due:
                    ret.append(Upcoming.from_trip(trip, stop_id, 'SCHEDULE', due,
                                                now(), canceled=False,
                                                added_to_schedule=False))

        SCHEDULED_RETURNED.observe(len(ret))
        trace.get_current_span().set_attribute(TRACE_PREFIX + 'scheduled', len(ret))

        return sorted(ret, key=lambda x: x.due_in_seconds)

    @LIVE_TIME.time()
    @tracer.start_as_current_span("GetLive")
    def get_live(self, interesting_stops: list[str]) -> list[Upcoming]:
        resp = self.load_from_api()
        ret = []
        early = 0
        delayed = 0
        ontime = 0
        not_update = 0
        unexpected_schedule_relationship = 0
        trips_added = 0
        trips_canceled = 0

        current = now()

        for entity in resp.entity:
            if not entity.HasField('trip_update'):
                not_update += 1
                continue

            trip_update = entity.trip_update
            trip = trip_update.trip

            scheduled = (trip.schedule_relationship ==
                        gtfs_realtime_pb2.TripDescriptor.SCHEDULED)
            canceled = (trip.schedule_relationship ==
                       gtfs_realtime_pb2.TripDescriptor.CANCELED)
            added = (trip.schedule_relationship ==
                    gtfs_realtime_pb2.TripDescriptor.ADDED)

            trip_from_db = self._database.get_trip(trip.trip_id)
            if not trip_from_db and added:
                trip_from_db = self._build_trip_from_update(trip_update,
                                                          interesting_stops)

            if not trip_from_db:
                continue

            if not (scheduled or canceled or added):
                sr = gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship.Name(
                    trip.schedule_relationship)
                logger.warning('received unexpected schedule_relationship for '
                             'trip_id %s: %s', trip.trip_id, sr)
                unexpected_schedule_relationship += 1
                continue

            sequence = -1
            arrival_time = datetime.datetime.fromtimestamp(1)
            stop_id = ""

            for stop_time in trip_from_db.stop_times:
                if stop_time['stop_id'] in interesting_stops:
                    stop_id = stop_time['stop_id']
                    sequence = int(stop_time['stop_sequence'])
                    arrival_time = parse_time(stop_time['arrival_time'])
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
                trips_canceled += 1

            if added:
                trips_added += 1

            ret.append(Upcoming.from_trip(trip_from_db, stop_id, 'LIVE',
                                        updated_arrival_time, current,
                                        canceled=canceled,
                                        added_to_schedule=added))

        MATCHED_TRIPS.labels('ontime').observe(ontime)
        MATCHED_TRIPS.labels('early').observe(early)
        MATCHED_TRIPS.labels('delayed').observe(delayed)
        ENTITIES_IGNORED.labels('wrong_type').observe(not_update)
        ENTITIES_IGNORED.labels('not_scheduled').observe(unexpected_schedule_relationship)
        ENTITIES_RETURNED.observe(len(resp.entity))

        trace.get_current_span().set_attributes({
            TRACE_PREFIX + 'matched-ontime': ontime,
            TRACE_PREFIX + 'matched-early': early,
            TRACE_PREFIX + 'matched-delayed': delayed,
            TRACE_PREFIX + 'matched-canceled': trips_canceled,
            TRACE_PREFIX + 'ignored-wrong_type': not_update,
            TRACE_PREFIX + 'ignored-unexpected_schedule_relationship': unexpected_schedule_relationship,
            TRACE_PREFIX + 'ignored-added': trips_added,
            TRACE_PREFIX + 'entities-returned': len(resp.entity),
        })

        return ret

    @UPCOMING_TIME.time()
    @tracer.start_as_current_span("GetUpcoming")
    def get_upcoming(self, interesting_stops: list[str]) -> list[Upcoming]:
        ret: list[Upcoming] = []

        scheduled = self.get_scheduled(interesting_stops)
        known_trips = {s.trip_id: s for s in scheduled}
        known_count = 0

        ret = self.get_live(interesting_stops)
        for trip in ret:
            if trip.trip_id in known_trips:
                del known_trips[trip.trip_id]
                known_count += 1

        for value in known_trips.values():
            ret.append(value)

        SCHEDULED_AND_LIVE.observe(known_count)
        trace.get_current_span().set_attribute(TRACE_PREFIX + 'matched-live',
                                             known_count)

        # Remove canceled trips, sort ascending by due_in_seconds.
        return sorted(filter(lambda t: not t.canceled, ret),
                     key=lambda x: x.due_in_seconds)
