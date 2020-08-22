import gtfs_data.loader

import unittest

TEST_FILE = 'gtfs_data/testdata/agency.txt'
TEST_FILE_BROKEN_CHARACTER = 'gtfs_data/testdata/calendar.txt'
FIRST_ROW = {
  'agency_id': '03C',
  'agency_name': 'GoAhead Commuter',
  'agency_url': 'https://www.transportforireland.ie',
  'agency_timezone': 'Europe/Dublin',
  'agency_lang': 'EN'
}

class TestLoader(unittest.TestCase):
  def testLoadAll(self):
    result = gtfs_data.loader.Load(TEST_FILE)
    self.assertEqual(len(result), 4)
    self.assertEqual(result[0], FIRST_ROW)


  def testLoadWithFilter(self):
    result = gtfs_data.loader.Load(TEST_FILE, {'agency_id': set(['03C'])})
    self.assertEqual(len(result), 1)
    self.assertEqual(result[0], FIRST_ROW)

  def testLoadWithMultiFilter(self):
    result = gtfs_data.loader.Load(TEST_FILE, {
      'agency_id':   set(['03C', '978']),
      'agency_lang': set(['EN'])})

    self.assertEqual(len(result), 2)
    self.assertEqual(result[0]['agency_id'], '03C')
    self.assertEqual(result[1]['agency_id'], '978')

  def testBrokenCharacterRemoval(self):
    result = gtfs_data.loader.Load(TEST_FILE_BROKEN_CHARACTER)
    self.assertIn('service_id', result[0].keys())

if __name__ == '__main__':
    unittest.main()
