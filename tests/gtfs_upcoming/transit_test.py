import datetime
import unittest
import unittest.mock

from google.protobuf import json_format
from google.transit import gtfs_realtime_pb2  # type: ignore[import]

import gtfs_upcoming.schedule
from gtfs_upcoming import transit

TEST_FEEDMESSAGE_ONE = 'testdata/gtfsv1-sample-onetrip.json'
TEST_FEEDMESSAGE_TWO = 'testdata/gtfsv1-sample-twotrips.json'
TEST_FEEDMESSAGE_CANCELED = 'testdata/gtfsv1-sample-canceled.json'
TEST_FEEDMESSAGE_ADDED = 'testdata/gtfsv1-sample-added.json'
TEST_FEEDMESSAGE_UNEXPECTED_RELATIONSHIPS = 'testdata/gtfsv1-sample-unexpected-relationships.json'
TEST_FEEDMESSAGE_MISSING_TRIP_UPDATE = 'testdata/gtfsv1-sample-missing-trip-update.json'
TEST_FEEDMESSAGE_UNKNOWN_TRIP = 'testdata/gtfsv1-sample-unknown-trip.json'
INTERESTING_STOPS = ['8250DB003076']    # seq 30 for 1167, 25 for 1169
GTFS_DATA = 'testdata/schedule'

def fetch(input_file: str):
  """Simulates a real API call."""
  with open(input_file) as f:
    json_data = f.read()

  pb = json_format.Parse(json_data, gtfs_realtime_pb2.FeedMessage())
  return pb.SerializeToString()

class TestTransit(unittest.TestCase):
  def setUp(self):
    database = gtfs_upcoming.schedule.Database(GTFS_DATA, INTERESTING_STOPS)
    database.load()

    self.fetch_input = TEST_FEEDMESSAGE_TWO
    self.transit = transit.Transit(self.fetch, database)

  def fetch(self):
    """Simple wrapper to allow a test to specify which file it wants."""
    return fetch(self.fetch_input)

  def test_parse_time(self):
    now_time = transit.now()

    # Same day
    assert (transit.parse_time("22:20:00").date() -
            now_time.date() == datetime.timedelta(days=0))

    # +1 day
    assert (transit.parse_time("24:20:00").date() -
            now_time.date() == datetime.timedelta(days=1))
    assert (transit.parse_time("27:20:00").date() -
            now_time.date() == datetime.timedelta(days=1))

    # +2 days
    assert (transit.parse_time("48:20:00").date() -
            now_time.date() == datetime.timedelta(days=2))
    assert (transit.parse_time("49:20:00").date() -
            now_time.date() == datetime.timedelta(days=2))

    # Test the hours
    assert transit.parse_time("15:20:00").time().hour == 15
    assert transit.parse_time("27:20:00").time().hour == 3
    assert transit.parse_time("49:20:00").time().hour == 1

  def test_delta_seconds(self):
    now = datetime.datetime(2023, 8, 21)
    t1 = datetime.datetime.combine(now, datetime.time(10, 40, 00))
    t2 = datetime.datetime.combine(now, datetime.time(10, 45, 30))
    t3 = datetime.datetime.combine(now, datetime.time(15, 40, 00))

    assert transit.delta_seconds(t1, t2) == -330
    assert transit.delta_seconds(t2, t1) == 330
    assert transit.delta_seconds(t3, t1) == 18000

  def test_get_live(self):
    with unittest.mock.patch('gtfs_upcoming.transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 8, 20, 7, 0, 0)

        resp = self.transit.get_live(INTERESTING_STOPS)

        assert len(resp) == 2

        # Scheduled is 07:20:16, transit data reflects a 4 minute delay (240 secs) so we expect
        # the due time at 07:24:16.
        assert resp[0].route == '7A'
        assert resp[0].due_time == '07:24:16'

        # Scheduled arrival is 08:04:11, no delay.
        assert resp[1].route == '7'
        assert resp[1].due_time == '08:04:11'

  def test_get_live_ignore_passed_stop(self):
    """Same as test_get_live except the mock time is 1 hour later.

    At this time, route 7A  (trip 1167) has passed the stop of interest so it should
    not come back in the dataset.
    """
    with unittest.mock.patch('gtfs_upcoming.transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 8, 20, 8, 0, 0)

        resp = self.transit.get_live(INTERESTING_STOPS)

        assert len(resp) == 1

        # Scheduled arrival is 08:04:11, no delay.
        assert resp[0].route == '7'
        assert resp[0].due_time == '08:04:11'
        assert not resp[0].canceled

  def test_get_scheduled(self):
    with unittest.mock.patch('gtfs_upcoming.transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 11, 19, 7, 00, 0)

        resp = self.transit.get_scheduled(INTERESTING_STOPS)
        assert len(resp) == 2
        assert resp[0].route == '7A'
        assert resp[0].due_time == '07:20:16'
        assert resp[0].source == 'SCHEDULE'
        assert resp[1].route == '7'
        assert resp[1].due_time == '08:04:11'
        assert resp[1].source == 'SCHEDULE'

  def test_get_scheduled_ignore_passed_stop(self):
    """Same as test_get_live except the mock time is 1 hour later."""
    with unittest.mock.patch('gtfs_upcoming.transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 11, 19, 8, 00, 0)

        resp = self.transit.get_scheduled(INTERESTING_STOPS)
        assert len(resp) == 1
        assert resp[0].route == '7'
        assert resp[0].due_time == '08:04:11'
        assert resp[0].source == 'SCHEDULE'

  def test_get_upcoming(self):
    # Use only one trip; this means get_upcoming will have to merge the live
    # and schedule.
    self.fetch_input = TEST_FEEDMESSAGE_ONE

    with unittest.mock.patch('gtfs_upcoming.transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 11, 19, 7, 00, 0)

        resp = self.transit.get_upcoming(INTERESTING_STOPS)
        assert len(resp) == 2
        assert resp[0].route == '7A'
        assert resp[0].due_time == '07:24:16'
        assert resp[0].source == 'LIVE'
        assert resp[1].route == '7'
        assert resp[1].due_time == '08:04:11'
        assert resp[1].source == 'SCHEDULE'

  def test_get_live_with_cancel(self):
    # Use only one trip; this means get_upcoming will have to merge the live
    # and schedule.
    self.fetch_input = TEST_FEEDMESSAGE_CANCELED

    with unittest.mock.patch('gtfs_upcoming.transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 11, 19, 7, 00, 0)

        resp = self.transit.get_live(INTERESTING_STOPS)
        assert len(resp) == 2
        assert resp[0].route == '7A'
        assert resp[0].due_time == '07:24:16'
        assert resp[0].source == 'LIVE'
        assert not resp[0].canceled
        assert resp[1].route == '7'
        assert resp[1].due_time == '08:04:11'
        assert resp[1].source == 'LIVE'
        assert resp[1].canceled

  def test_get_upcoming_with_cancel(self):
    # Use only one trip; this means get_upcoming will have to merge the live
    # and schedule.
    self.fetch_input = TEST_FEEDMESSAGE_CANCELED

    with unittest.mock.patch('gtfs_upcoming.transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 11, 19, 7, 00, 0)

        resp = self.transit.get_upcoming(INTERESTING_STOPS)
        assert len(resp) == 1
        assert resp[0].route == '7A'
        assert resp[0].due_time == '07:24:16'
        assert resp[0].source == 'LIVE'
        assert not resp[0].canceled

  def test_get_live_with_added(self):
    # Use only one trip; this means get_upcoming will have to merge the live
    # and schedule.
    self.fetch_input = TEST_FEEDMESSAGE_ADDED

    with unittest.mock.patch('gtfs_upcoming.transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 11, 19, 7, 00, 0)

        resp = self.transit.get_live(INTERESTING_STOPS)
        assert len(resp) == 2
        assert resp[0].route == '7A'
        assert resp[0].due_time == '07:24:16'
        assert resp[0].source == 'LIVE'
        assert not resp[0].canceled

        assert resp[1].trip_id == 'AddedTrip'
        assert resp[1].route == '7'

        # A little hack here to avoid timezone shenaniganery. The translation processes use a mix of
        # absolute UNIX times & H:M:S local-times (see the stop_times db). This makes this test
        # sensitive to running outside the timezone of the GTFS Schedule data.
        dep_time_in_test = 1605771000
        dep_time_in_local_tz = datetime.datetime.fromtimestamp(dep_time_in_test).strftime("%H:%M:%S")

        assert resp[1].due_time == dep_time_in_local_tz
        assert resp[1].source == 'LIVE'

  def test_get_live_unexpected_schedule_relationships(self):
    """Test handling of unexpected schedule relationship values."""
    
    # Use the test data file with unexpected schedule relationships
    self.fetch_input = TEST_FEEDMESSAGE_UNEXPECTED_RELATIONSHIPS
    
    with unittest.mock.patch('gtfs_upcoming.transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 8, 20, 7, 0, 0)
        
        # Capture log messages to verify warnings are logged
        with self.assertLogs('gtfs_upcoming.transit', level='WARNING') as log_context:
            resp = self.transit.get_live(INTERESTING_STOPS)
        
        # Should only return the valid trip, not the ones with unexpected relationships
        assert len(resp) == 1
        assert resp[0].trip_id == "1167"
        assert resp[0].route == "7A"
        assert resp[0].due_time == "07:24:16"  # Original time + 4 minute delay
        assert resp[0].source == "LIVE"
        assert not resp[0].canceled
        
        # Verify that warnings were logged for unexpected relationships
        warning_messages = [record.message for record in log_context.records]
        assert len(warning_messages) == 2
        
        # Check that both unexpected relationships were logged
        unexpected_warnings = [msg for msg in warning_messages if "unexpected schedule_relationship" in msg]
        assert len(unexpected_warnings) == 2
        
        # Verify the specific trip IDs were mentioned in warnings
        assert any("1167" in msg for msg in unexpected_warnings)
        assert any("1169" in msg for msg in unexpected_warnings)
        
        # Verify the specific relationship names were mentioned
        assert any("UNSCHEDULED" in msg for msg in unexpected_warnings)
        assert any("REPLACEMENT" in msg for msg in unexpected_warnings)

  def test_get_live_missing_trip_update_field(self):
    """Test handling of entities without trip_update field."""
    
    # Use the test data file with missing trip_update field
    self.fetch_input = TEST_FEEDMESSAGE_MISSING_TRIP_UPDATE
    
    with unittest.mock.patch('gtfs_upcoming.transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 8, 20, 7, 0, 0)
        
        resp = self.transit.get_live(INTERESTING_STOPS)
        
        # Should only return the valid trip
        assert len(resp) == 1
        assert resp[0].trip_id == "1167"

  def test_get_live_trip_not_in_database(self):
    """Test handling of trips that don't exist in the schedule database."""
    
    # Use the test data file with unknown trip
    self.fetch_input = TEST_FEEDMESSAGE_UNKNOWN_TRIP
    
    with unittest.mock.patch('gtfs_upcoming.transit.now') as mock_now:
        mock_now.return_value = datetime.datetime(2020, 8, 20, 7, 0, 0)
        
        resp = self.transit.get_live(INTERESTING_STOPS)
        
        # Should only return the valid trip, unknown trip should be ignored
        assert len(resp) == 1
        assert resp[0].trip_id == "1167"

if __name__ == '__main__':
    unittest.main()
