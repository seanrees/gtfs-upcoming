import gtfs_data.database

import datetime
import unittest

TEST_FILE = 'gtfs_data/testdata/agency.txt'
GTFS_DATA = 'gtfs_data/testdata'
INTERESTING_STOPS = ['8220DB000490']


class TestDatabase(unittest.TestCase):
  def setUp(self):
    self.database = gtfs_data.database.Database(GTFS_DATA, INTERESTING_STOPS)

  def test_Load(self):
    data = self.database._Load('agency.txt')
    self.assertEqual(len(data), 4)

  def test_Collect(self):
    data = [
      {'a': 'one', 'b': 200},
      {'a': 'one', 'b': 300},
      {'a': 'two', 'b': 400},
    ]

    c = self.database._Collect(data, 'a')
    self.assertEqual(c, {
      'one': {'a': 'one', 'b': 300},
      'two': {'a': 'two', 'b': 400}})

    c = self.database._Collect(data, 'a', multi=True)
    self.assertEqual(c, {
      'one': [{'a': 'one', 'b': 200}, {'a': 'one', 'b': 300}],
      'two': [{'a': 'two', 'b': 400}]})

  def testGetTrip(self):
    self.database.Load()
    found = self.database.GetTrip('1167')
    self.assertIsNotNone(found)
    self.assertEqual(found.trip_headsign, 'Loughlinstown Wood Estate - Mountjoy Square Nth')

    notfound = self.database.GetTrip('1168')
    self.assertIsNone(notfound)

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

    self.assertEqual(len(self.database._trip_db.keys()), 2)

    for trip_id, t in self.database._trip_db.items():
      self.assertIn(t.trip_id, trips.keys())
      data = trips[t.trip_id]

      self.assertEqual(t.direction_id, data['direction_id'])
      self.assertEqual(t.trip_headsign, data['trip_headsign'])
      self.assertIsNotNone(t.route)
      self.assertEqual(t.route['route_short_name'], data['route_short_name'])
      self.assertIsNotNone(t.stop_times)
      self.assertEqual(len(t.stop_times), data['num_stop_times'])

  def testLoadAll(self):
    database = gtfs_data.database.Database(GTFS_DATA, [])
    database.Load()
    self.assertEqual(database._trip_db.keys(), set(['1167', '1168', '1169']))


  def testGetScheduledFor(self):
    database = gtfs_data.database.Database(GTFS_DATA, [])
    database.Load()

    stop_id = INTERESTING_STOPS[0]
    start = datetime.datetime(2020, 11, 19, 7, 30, 00)
    stop = datetime.datetime(2020, 11, 19, 8, 30, 00)
    resp = database.GetScheduledFor(stop_id, start, stop)

    # Note: GetScheduledFor sorts on arrival time; so the order here is
    # predictable.
    self.assertEqual(len(resp), 2)
    self.assertEqual(resp[0].trip_id, '1167')
    self.assertEqual(resp[1].trip_id, '1169')

    # This trip's schedule has no exceptions; ensure we don't error
    # out loading it. Note: the stop id below is not in INTERESTING_STOPS
    # so we don't get it by default from setUp().
    stop_id = '8220DB000819'
    start = datetime.datetime(2020, 11, 19, 20, 00, 00)
    stop = datetime.datetime(2020, 11, 19, 21, 00, 00)
    resp = database.GetScheduledFor(stop_id, start, stop)
    self.assertEqual(len(resp), 1)
    self.assertEqual(resp[0].trip_id, '1168')


  def testGetScheduledForExceptions(self):
    self.database.Load()

    # We have an exception for this date ("no service").
    stop_id = INTERESTING_STOPS[0]
    start = datetime.datetime(2020, 11, 26, 7, 30, 00)
    stop = datetime.datetime(2020, 11, 26, 8, 30, 00)
    resp = self.database.GetScheduledFor(stop_id, start, stop)
    self.assertEqual(len(resp), 0)

    # We have an exception for this date ("added service").
    stop_id = INTERESTING_STOPS[0]
    start = datetime.datetime(2020, 11, 27, 7, 30, 00)
    stop = datetime.datetime(2020, 11, 27, 8, 30, 00)
    resp = self.database.GetScheduledFor(stop_id, start, stop)
    self.assertEqual(len(resp), 2)

if __name__ == '__main__':
    unittest.main()
