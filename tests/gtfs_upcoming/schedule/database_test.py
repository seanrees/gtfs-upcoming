import datetime
import multiprocessing
import unittest

import pytest

from gtfs_upcoming.schedule import CALENDAR_DAYS, Database

TEST_FILE = 'testdata/schedule/agency.txt'
GTFS_DATA = 'testdata/schedule'
INTERESTING_STOPS = ['8220DB000490']


class TestDatabase(unittest.TestCase):
  def setUp(self):
    self.database = Database(GTFS_DATA, INTERESTING_STOPS)

  def test_Load(self):
    data = self.database._Load('agency.txt')
    assert len(data) == 4

  def test_Collect(self):
    data = [
      {'a': 'one', 'b': 200},
      {'a': 'one', 'b': 300},
      {'a': 'two', 'b': 400},
    ]

    c = self.database._Collect(data, 'a')
    assert c == {
      'one': {'a': 'one', 'b': 300},
      'two': {'a': 'two', 'b': 400}}

    c = self.database._Collect(data, 'a', multi=True)
    assert c == {
      'one': [{'a': 'one', 'b': 200}, {'a': 'one', 'b': 300}],
      'two': [{'a': 'two', 'b': 400}]}

  def testGetTrip(self):
    self.database.Load()
    found = self.database.GetTrip('1167')
    assert found is not None
    assert found.trip_headsign == 'Loughlinstown Wood Estate - Mountjoy Square Nth'

    notfound = self.database.GetTrip('1168')
    assert notfound is None

  def testLoad(self):
    self.database.Load()

    trips = {
      '1167': {
        'direction_id': '1',
        'trip_headsign': 'Loughlinstown Wood Estate - Mountjoy Square Nth',
        'route_short_name': '7A',
        'num_stop_times': 64,
      },
      '1169': {
        'direction_id': '1',
        'trip_headsign': 'Bride\'s Glen Bus Stop - Mountjoy Square Nth',
        'route_short_name': '7',
        'num_stop_times': 56
      }
    }

    assert len(self.database._trip_db.keys()) == 2

    for t in self.database._trip_db.values():
      assert t.trip_id in trips
      data = trips[t.trip_id]

      assert t.direction_id == data['direction_id']
      assert t.trip_headsign == data['trip_headsign']
      assert t.route is not None
      assert t.route['route_short_name'] == data['route_short_name']
      assert t.stop_times is not None
      assert len(t.stop_times) == data['num_stop_times']

  def testLoadAll(self):
    database = Database(GTFS_DATA, [])
    database.Load()
    assert database._trip_db.keys() == {'1167', '1168', '1169', 'ONIGHT'}

  def testGetScheduledFor(self):
    database = Database(GTFS_DATA, [])
    database.Load()

    stop_id = INTERESTING_STOPS[0]
    start = datetime.datetime(2020, 11, 19, 7, 30, 00)
    stop = datetime.datetime(2020, 11, 19, 8, 30, 00)
    resp = database.GetScheduledFor(stop_id, start, stop)

    # Note: GetScheduledFor sorts on arrival time; so the order here is
    # predictable.
    assert len(resp) == 2
    assert resp[0].trip_id == '1167'
    assert resp[1].trip_id == '1169'

    # This trip's schedule has no exceptions; ensure we don't error
    # out loading it. Note: the stop id below is not in INTERESTING_STOPS
    # so we don't get it by default from setUp().
    stop_id = '8220DB000819'
    start = datetime.datetime(2020, 11, 19, 20, 00, 00)
    stop = datetime.datetime(2020, 11, 19, 21, 00, 00)
    resp = database.GetScheduledFor(stop_id, start, stop)
    assert len(resp) == 1
    assert resp[0].trip_id == '1168'

  def testGetScheduledForOvernightRoutes(self):
    """Test schedule generation for routes that span days"""
    database = Database(GTFS_DATA, [])
    database.Load()

    stop_id = 'ONIGHT-STOP2'

    start = datetime.datetime(2020, 11, 19, 23, 00, 00)
    stop = datetime.datetime(2020, 11, 20, 2, 00, 00)
    resp = database.GetScheduledFor(stop_id, start, stop)
    assert len(resp) == 1
    assert resp[0].trip_id == 'ONIGHT'

    start = datetime.datetime(2020, 11, 20, 0, 00, 00)
    stop = datetime.datetime(2020, 11, 20, 2, 00, 00)
    resp = database.GetScheduledFor(stop_id, start, stop)
    assert len(resp) == 1
    assert resp[0].trip_id == 'ONIGHT'

    start = datetime.datetime(2020, 11, 18, 23, 00, 00)
    stop = datetime.datetime(2020, 11, 20, 2, 00, 00)
    resp = database.GetScheduledFor(stop_id, start, stop)
    assert len(resp) == 2
    assert resp[0].trip_id == 'ONIGHT'
    assert resp[0].trip_id == 'ONIGHT'

  def testGetScheduledForInvalids(self):
    self.database.Load()

    start = datetime.datetime(2020, 11, 20, 0, 00, 00)
    stop = datetime.datetime(2020, 11, 20, 2, 00, 00)

    # Invalid stop.
    resp = self.database.GetScheduledFor("foo", start, stop)
    assert len(resp) == 0

    # Invalid times.
    with pytest.raises(ValueError, match="start must come before end"):
      self.database.GetScheduledFor(INTERESTING_STOPS[0], stop, start)

  def testGetScheduledForExceptions(self):
    self.database.Load()

    # We have an exception for this date ("no service").
    stop_id = INTERESTING_STOPS[0]
    start = datetime.datetime(2020, 11, 26, 7, 30, 00)
    stop = datetime.datetime(2020, 11, 26, 8, 30, 00)
    resp = self.database.GetScheduledFor(stop_id, start, stop)
    assert len(resp) == 0

    # We have an exception for this date ("added service").
    stop_id = INTERESTING_STOPS[0]
    start = datetime.datetime(2020, 11, 27, 7, 30, 00)
    stop = datetime.datetime(2020, 11, 27, 8, 30, 00)
    resp = self.database.GetScheduledFor(stop_id, start, stop)
    assert len(resp) == 2

  def testIsValidServiceDay(self):
    database = Database(GTFS_DATA, [])
    database.Load()

    # The exceptions only apply to trips 1167 and 1169. Trip 1168 has no exceptions
    # but we should check to make sure it still behaves normally.
    removed_service_date = datetime.date(2020, 11, 26)
    assert not database._IsValidServiceDay(removed_service_date, '1167')
    assert not database._IsValidServiceDay(removed_service_date, '1169')
    assert database._IsValidServiceDay(removed_service_date, '1168')

    added_service_date = datetime.date(2020, 11, 27)
    assert database._IsValidServiceDay(added_service_date, '1167')
    assert database._IsValidServiceDay(added_service_date, '1169')
    assert database._IsValidServiceDay(added_service_date, '1168')

    normal_service_date  = datetime.date(2020, 11, 19)
    assert database._IsValidServiceDay(normal_service_date, '1167')
    assert database._IsValidServiceDay(normal_service_date, '1169')
    assert database._IsValidServiceDay(normal_service_date, '1168')

    normal_no_service_date = datetime.date(2020, 11, 28)
    assert not database._IsValidServiceDay(normal_no_service_date, '1167')
    assert not database._IsValidServiceDay(normal_no_service_date, '1169')
    assert not database._IsValidServiceDay(normal_no_service_date, '1168')

    # 1167 and 1169 are Thursday only, 1168 is M-F -- so lets use 1168
    # Valid dates for the schedule are 2020-11-04 to 2021-02-25
    before_start_date = datetime.date(2020, 11, 3)
    assert not database._IsValidServiceDay(before_start_date, '1168')

    start_date = datetime.date(2020, 11, 4)
    assert database._IsValidServiceDay(start_date, '1168')

    end_date = datetime.date(2021, 2, 25)
    assert database._IsValidServiceDay(end_date, '1168')

    after_end_date = datetime.date(2020, 2, 26)
    assert not database._IsValidServiceDay(after_end_date, '1168')


  def testNumberOfDays(self):
    assert len(CALENDAR_DAYS) == 7

if __name__ == '__main__':
    multiprocessing.set_start_method("spawn")
    unittest.main()
