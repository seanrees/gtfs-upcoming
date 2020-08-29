import urllib.request

import prometheus_client    # type: ignore[import]


TEST_URL = "https://api.nationaltransport.ie/gtfsrtest/"
PROD_URL = "https://gtfsr.transportforireland.ie/v1"

# Metrics
LATENCY = prometheus_client.Summary(
  'gtfs_request_latency_seconds',
  'Request latency to GTFS API service')

RESPONSE_BYTES = prometheus_client.Summary(
  'gtfs_response_bytes',
  'Response bytes from GTFS API service')

RESPONSE_STATUS = prometheus_client.Counter(
  'gtfs_response_status_codes',
  'HTTP response codes from GTFS API service',
  ['code'])

REQUESTS = prometheus_client.Counter(
  'gtfs_requests_total',
  'Requests to GTFS API service')


@LATENCY.time()
def Fetch(api_key: str, url: str=TEST_URL) -> bytes:
  """Fetches the GTFS data"""
  headers = {
    "Cache-Control": "no-cache",
    "x-api-key": api_key
  }

  REQUESTS.inc()

  req = urllib.request.Request(url, None, headers)
  with urllib.request.urlopen(req) as f:
    out = f.read()
    RESPONSE_STATUS.labels(f.status).inc()

  RESPONSE_BYTES.observe(len(out))
  return out
