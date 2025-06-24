import unittest

from gtfs_upcoming.schedule import loader

TEST_FILE = 'testdata/schedule/agency.txt'
TEST_FILE_BROKEN_CHARACTER = 'testdata/schedule/calendar.txt'
FIRST_ROW = {
    'agency_id': '03C',
    'agency_name': 'GoAhead Commuter',
    'agency_url': 'https://www.transportforireland.ie',
    'agency_timezone': 'Europe/Dublin',
    'agency_lang': 'EN'
}


class TestLoader(unittest.TestCase):
    def test_load_all(self):
        result = loader.Load(TEST_FILE)
        assert len(result) == 4
        assert result[0] == FIRST_ROW

    def test_load_with_filter(self):
        result = loader.Load(TEST_FILE, {'agency_id': {'03C'}})
        assert len(result) == 1
        assert result[0] == FIRST_ROW

    def test_load_with_multi_filter(self):
        result = loader.Load(TEST_FILE, {
            'agency_id': {'03C', '978'},
            'agency_lang': {'EN'}})

        assert len(result) == 2
        assert result[0]['agency_id'] == '03C'
        assert result[1]['agency_id'] == '978'

    def test_broken_character_removal(self):
        result = loader.Load(TEST_FILE_BROKEN_CHARACTER)
        assert 'service_id' in result[0]


if __name__ == '__main__':
    unittest.main()
