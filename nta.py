import urllib.request

TEST_URL = "https://api.nationaltransport.ie/gtfsrtest/"
PROD_URL = "https://gtfsr.transportforireland.ie/v1"

def Fetch(api_key: str, url: str=TEST_URL) -> bytes:
  """Fetches the GTFS data"""
  headers = {
    "Cache-Control": "no-cache",
    "x-api-key": api_key
  }

  req = urllib.request.Request(url, None, headers)
  with urllib.request.urlopen(req) as f:
    out = f.read()

  return out
