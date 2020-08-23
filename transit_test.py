import aapipfix
import gtfs_data.database
import transit

from google.protobuf import json_format
from google.transit import gtfs_realtime_pb2    # type: ignore[import]

import datetime
import unittest
import unittest.mock

TEST_FEEDMESSAGE = 'testdata/gtfsv1-sample.json'
INTERESTING_STOPS = ['8250DB003076']    # seq 30 for 1167, 25 for 1169
GTFS_DATA = 'gtfs_data/testdata'

def fetch():
  """Simulates a real API call."""
  with open(TEST_FEEDMESSAGE, 'r') as f:
    json = f.read()

  pb = json_format.Parse(json, gtfs_realtime_pb2.FeedMessage())
  return pb.SerializeToString()

class TestTransit(unittest.TestCase):
  def setUp(self):
    database = gtfs_data.database.Database(GTFS_DATA, INTERESTING_STOPS)
    database.Load()

    self.transit = transit.Transit(fetch, database)

  def testDelta_Seconds(self):
    t1 = datetime.time(10, 40, 00)
    t2 = datetime.time(10, 45, 30)
    t3 = datetime.time(15, 40, 00)

    self.assertEqual(transit.delta_seconds(t1, t2), -330)
    self.assertEqual(transit.delta_seconds(t2, t1), 330)
    self.assertEqual(transit.delta_seconds(t3, t1), 18000)

  def testGetUpcoming(self):
    with unittest.mock.patch('transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 8, 21, 7, 0, 0)

        resp = self.transit.GetUpcoming(INTERESTING_STOPS)

        self.assertEqual(2, len(resp))

        # Scheduled is 07:20:16, transit data reflects a 4 minute delay (240 secs) so we expect
        # the due time at 07:24:16.
        self.assertEqual(resp[0].route, '7A')
        self.assertEqual(resp[0].dueTime, '07:24:16')

        # Scheduled arrival is 08:04:11, no delay.
        self.assertEqual(resp[1].route, '7')
        self.assertEqual(resp[1].dueTime, '08:04:11')

  def testGetUpcomingIgnorePassedStop(self):
    """Same as testGetUpcoming except the mock time is 1 hour later.

    At this time, route 7A  (trip 1167) has passed the stop of interest so it should
    not come back in the dataset.
    """
    with unittest.mock.patch('transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 8, 21, 8, 0, 0)

        resp = self.transit.GetUpcoming(INTERESTING_STOPS)

        self.assertEqual(1, len(resp))

        # Scheduled arrival is 08:04:11, no delay.
        self.assertEqual(resp[0].route, '7')
        self.assertEqual(resp[0].dueTime, '08:04:11')


if __name__ == '__main__':
    unittest.main()
