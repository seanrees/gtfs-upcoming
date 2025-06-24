from __future__ import annotations

import collections
import datetime
import logging
import os
from collections.abc import Set as AbstractSet
from typing import Any, NamedTuple

import prometheus_client  # type: ignore[import]
from opentelemetry import trace

from . import loader

logger = logging.getLogger(__name__)


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

SCHEDULE_RESPONSE = prometheus_client.Summary(
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

TRACE_PREFIX = 'gtfs-upcoming.schedule.database.'

tracer = trace.get_tracer("tracer.schedule.database")


class Trip(NamedTuple):
    trip_id: str
    trip_headsign: str
    direction_id: str
    service_id: str
    route: Route
    stop_times: list[dict[str, str]]


class Route(NamedTuple):
    route_id: str
    short_name: str
    long_name: str
    route_type: str
    inferred_headsign: str
    inferred_direction_id: str
    inferred_service_id: str


class Database:
    """Provides an easy-to-query interface for the GTFS database.

    This is not a generic API; this is tailored to the specific use-case of this
    application.
    """

    def __init__(self, data_dir: str, keep_stops: list[str]):
        """Initialises and loads the database.

        Args:
            data_dir: path to the GTFS data package
            keep_stops: a list of stops to filter the database data on. If keep_stops is empty,
                ALL stops are kept.
        """
        self._data_dir = data_dir
        self._keep_stops = keep_stops
        self._load_all_stops = len(keep_stops) == 0
        self._stops_db: dict[str, list[dict[str, str]]] = {}
        self._trip_db: dict[str, Trip] = {}
        self._route_db: dict[str, Route] = {}
        self._calendar_db: dict[str, dict[str, str]] = {}
        self._exceptions_db: dict[str, dict[datetime.date, str]] = {}

    @DATABASE_LOAD.time()
    def load(self):
        self._stops_db = self._load_stops()
        self._trip_db, self._route_db = self._load_trips()
        self._calendar_db = self._load_calendar()
        self._exceptions_db = self._load_exceptions()

        TRIPDB.observe(len(self._trip_db.keys()))

    def get_trip(self, trip_id: str):
        ret = self._trip_db.get(trip_id, None)
        TRIPDB_REQUESTS.labels(ret is not None).inc()
        return ret

    def get_route(self, route_id: str) -> Route | None:
        return self._route_db.get(route_id, None)

    def _is_valid_service_day(self, dt: datetime.date, trip: Trip) -> bool:
        service = self._calendar_db.get(trip.service_id, None)
        if not service:
            logger.error('service "%s" not found in database', trip.service_id)
            return False

        start = service['start_date']
        end = service['end_date']
        if dt < start or dt > end:  # type: ignore[operator]
            return False

        day = CALENDAR_DAYS[dt.weekday()]
        exc = self._exceptions_db.get(trip.service_id, {}).get(dt)
        if service.get(day) == CALENDAR_SERVICE_NOT_AVAILABLE:
            return exc == CALENDAR_EXCEPTION_SERVICE_ADDED

        return exc != CALENDAR_EXCEPTION_SERVICE_REMOVED

    @tracer.start_as_current_span("GetScheduledFor")
    def get_scheduled_for(self, stop_id: str, start: datetime.datetime,
                         end: datetime.datetime):
        """Returns the trips that are scheduled to stop at stop_id between start and end.

        Args:
            stop_id: stop id to look trips up for
            start: only return trips after this time
            end: only return trips that arrive before this time

        Return:
            list[Trip]
        """
        ret: list[Trip] = []

        stops = self._stops_db.get(stop_id, None)
        if not stops:
            logger.error('stop "%s" not found in database', stop_id)
            return ret

        if end < start:
            msg = 'start must come before end'
            raise ValueError(msg)

        one_day = datetime.timedelta(days=1)
        start_service_date = start.date() - one_day
        end_service_date = end.date()

        possibility = collections.namedtuple('possibility',
                                           ['service_date', 'arrival_time'])
        possibles_total = 0

        for s in stops:
            trip_id = s['trip_id']
            arrival_time_str = s['arrival_time']

            try:
                # GTFS's data format allows for hours >24 to indicate times the
                # next day. E.g; 25:00 = 0100+1; this is useful if a service starts
                # on one day and carries through to the next.
                hour, minute, second = (int(x) for x in arrival_time_str.split(':'))
                delta = datetime.timedelta(days=0)

                if hour >= 24:
                    delta = one_day
                    hour -= 24

                arrival_time_obj = datetime.time(hour=hour, minute=minute,
                                               second=second)

                possibles: list[possibility] = []
                service_date = start_service_date
                while service_date <= end_service_date:
                    arrival_time = (datetime.datetime.combine(service_date,
                                                             arrival_time_obj) +
                                   delta)
                    possibles.append(possibility(service_date, arrival_time))

                    service_date += one_day
            except ValueError:
                logger.exception('invalid format for arrival_time_str "%s"',
                               arrival_time_str)
                continue

            # These get reset every loop.
            possibles_total += len(possibles)

            for p in possibles:
                trip = self.get_trip(trip_id)
                if trip is None:
                    continue
                valid_day = self._is_valid_service_day(p.service_date, trip)
                if (valid_day and p.arrival_time >= start and
                    p.arrival_time <= end):
                    ret.append(trip)

        SCHEDULE_RESPONSE.observe(len(ret))
        trace.get_current_span().set_attributes({
            TRACE_PREFIX + 'stop_id': stop_id,
            TRACE_PREFIX + 'returned': len(ret),
            TRACE_PREFIX + 'possibles': possibles_total
        })

        return ret

    def _load_stops(self) -> dict[str, list[dict[str, str]]]:
        # First we need to extract the interesting trips and sequences.
        if self._load_all_stops:
            tmp_stop_times = self._load('stop_times.txt') or []
        else:
            tmp_stop_times = self._load('stop_times.txt', {'stop_id': set(self._keep_stops)}) or []

        result = self._collect(tmp_stop_times, 'stop_id', multi=True)
        if not isinstance(result, dict):
            result = {}
        result = dict(result)
        return {k: v if isinstance(v, list) else [v] for k, v in result.items()}

    def _load_trips(self) -> tuple[dict[str, Trip], dict[str, Route]]:
        trip_ids = set()
        for vals in self._stops_db.values():
            for stop in vals:
                trip_ids.add(stop['trip_id'])

        # Now collect the Trip->list of stops
        stop_times = self._collect(
            self._load('stop_times.txt', {'trip_id': trip_ids}) or [],
            'trip_id',
            multi=True) or {}

        # Lets load the routes.
        routes = self._collect(self._load('routes.txt') or [], 'route_id') or {}

        # Now let's produce the trip database.
        trips = self._collect(self._load('trips.txt', {'trip_id': trip_ids}) or [],
                            'trip_id') or {}

        trip_db = {}
        route_db = {}
        for trip_id, row in trips.items():
            route_id = row['route_id']
            if route_id not in routes:
                logger.debug('Trip "%s" references unknown route_id "%s" '
                           '(ignoring)', trip_id, route_id)
                continue

            st = stop_times.get(trip_id, None)
            if not st:
                logger.debug('Trip "%s" has no stop times', trip_id)
                st = []

            route = routes[route_id]
            if route_id not in route_db:
                # Routes don't contain a headsign or direction -- so we reuse the first trip we see with that
                # route id.
                route_db[route_id] = Route(
                    route_id, route['route_short_name'], route['route_long_name'],
                    route['route_type'],
                    inferred_headsign=row['trip_headsign'],
                    inferred_direction_id=row['direction_id'],
                    inferred_service_id=row['service_id'])

            t = Trip(trip_id, row['trip_headsign'], row['direction_id'],
                    row['service_id'], route_db[route_id], st)
            trip_db[trip_id] = t

        return (trip_db, route_db)

    def _load_calendar(self) -> dict[str, dict[str, str]]:
        """Loads calendar.txt."""
        dates = self._collect(self._load('calendar.txt') or [], 'service_id') or {}

        for data in dates.values():
            start = datetime.datetime.strptime(data['start_date'],
                                             '%Y%m%d').date()
            end = datetime.datetime.strptime(data['end_date'],
                                           '%Y%m%d').date()
            data['start_date'] = start
            data['end_date'] = end

        return dates

    def _load_exceptions(self) -> dict[str, dict[datetime.date, str]]:
        """Loads calendar_dates.txt and preparses dates for easy lookup."""
        dates = self._collect(self._load('calendar_dates.txt'), 'service_id',
                            multi=True)
        ret: dict[str, dict] = {service_id: {} for service_id in dates}

        for service_id, data in dates.items():
            for d in data:
                dt = datetime.datetime.strptime(d['date'], '%Y%m%d').date()
                ret[service_id][dt] = d['exception_type']

        return ret

    def _load(self, filename: str,
              keep: dict[str, AbstractSet[str]] | None = None):
        return loader.Load(
            os.path.join(os.path.join(self._data_dir, filename)),
            keep)

    def _collect(self, data: list[dict[str, str]], key_name: str,
                multi: bool = False):   # noqa: FBT001, FBT002
        if data is None:
            return {}
        ret: dict[str, Any] = {}

        duplicates = 0

        for row in data:
            if key_name not in row:
                logger.error('Key "%s" not found in row %s', key_name, row)
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
            logger.info('Detected %d duplicate %s keys', duplicates, key_name)

        return ret
