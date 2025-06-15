import datetime
import unittest
import unittest.mock

from google.protobuf import json_format
from google.transit import gtfs_realtime_pb2  # type: ignore[import]

import gtfs_upcoming.schedule
from gtfs_upcoming import transit

TEST_FEEDMESSAGE_ONE = 'testdata/gtfsv1-sample-onetrip.json'
TEST_FEEDMESSAGE_TWO = 'testdata/gtfsv1-sample-twotrips.json'
INTERESTING_STOPS = ['8250DB003076']    # seq 30 for 1167, 25 for 1169
GTFS_DATA = 'testdata/schedule'

def fetch(input_file: str):
  """Simulates a real API call."""
  with open(input_file) as f:
    json = f.read()

  pb = json_format.Parse(json, gtfs_realtime_pb2.FeedMessage())
  return pb.SerializeToString()

class TestTransit(unittest.TestCase):
  def setUp(self):
    database = gtfs_upcoming.schedule.Database(GTFS_DATA, INTERESTING_STOPS)
    database.Load()

    self.fetch_input = TEST_FEEDMESSAGE_TWO
    self.transit = transit.Transit(self.fetch, database)

  def fetch(self):
    """Simple wrapper to allow a test to specify which file it wants."""
    return fetch(self.fetch_input)

  def testParseTime(self):
    now = transit.now()
    assert transit.parseTime("24:20:00").date() - now.date() == datetime.timedelta(days=1)

  def testDelta_Seconds(self):
    now = datetime.datetime(2023, 8, 21)
    t1 = datetime.datetime.combine(now, datetime.time(10, 40, 00))
    t2 = datetime.datetime.combine(now, datetime.time(10, 45, 30))
    t3 = datetime.datetime.combine(now, datetime.time(15, 40, 00))

    assert transit.delta_seconds(t1, t2) == -330
    assert transit.delta_seconds(t2, t1) == 330
    assert transit.delta_seconds(t3, t1) == 18000

  def testGetLive(self):
    with unittest.mock.patch('gtfs_upcoming.transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 8, 20, 7, 0, 0)

        resp = self.transit.GetLive(INTERESTING_STOPS)

        assert len(resp) == 2

        # Scheduled is 07:20:16, transit data reflects a 4 minute delay (240 secs) so we expect
        # the due time at 07:24:16.
        assert resp[0].route == '7A'
        assert resp[0].dueTime == '07:24:16'

        # Scheduled arrival is 08:04:11, no delay.
        assert resp[1].route == '7'
        assert resp[1].dueTime == '08:04:11'

  def testGetLiveIgnorePassedStop(self):
    """Same as testGetLive except the mock time is 1 hour later.

    At this time, route 7A  (trip 1167) has passed the stop of interest so it should
    not come back in the dataset.
    """
    with unittest.mock.patch('gtfs_upcoming.transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 8, 20, 8, 0, 0)

        resp = self.transit.GetLive(INTERESTING_STOPS)

        assert len(resp) == 1

        # Scheduled arrival is 08:04:11, no delay.
        assert resp[0].route == '7'
        assert resp[0].dueTime == '08:04:11'

  def testGetScheduled(self):
    with unittest.mock.patch('gtfs_upcoming.transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 11, 19, 7, 00, 0)

        resp = self.transit.GetScheduled(INTERESTING_STOPS)
        assert len(resp) == 2
        assert resp[0].route == '7A'
        assert resp[0].dueTime == '07:20:16'
        assert resp[0].source == 'SCHEDULE'
        assert resp[1].route == '7'
        assert resp[1].dueTime == '08:04:11'
        assert resp[1].source == 'SCHEDULE'

  def testGetScheduledIgnorePassedStop(self):
    """Same as testGetLive except the mock time is 1 hour later."""
    with unittest.mock.patch('gtfs_upcoming.transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 11, 19, 8, 00, 0)

        resp = self.transit.GetScheduled(INTERESTING_STOPS)
        assert len(resp) == 1
        assert resp[0].route == '7'
        assert resp[0].dueTime == '08:04:11'
        assert resp[0].source == 'SCHEDULE'

  def testGetUpcoming(self):
    # Use only one trip; this means GetUpcoming will have to merge the live
    # and schedule.
    self.fetch_input = TEST_FEEDMESSAGE_ONE

    with unittest.mock.patch('gtfs_upcoming.transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 11, 19, 7, 00, 0)

        resp = self.transit.GetUpcoming(INTERESTING_STOPS)
        assert len(resp) == 2
        assert resp[0].route == '7A'
        assert resp[0].dueTime == '07:24:16'
        assert resp[0].source == 'LIVE'
        assert resp[1].route == '7'
        assert resp[1].dueTime == '08:04:11'
        assert resp[1].source == 'SCHEDULE'


if __name__ == '__main__':
    unittest.main()
