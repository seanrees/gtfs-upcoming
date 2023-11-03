import abc
import logging
import urllib.request

import prometheus_client    # type: ignore[import]



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


class Fetcher(abc.ABC):
  def request(self) -> urllib.request.Request:
    pass

  @LATENCY.time()
  def Fetch(self) -> bytes:
    """Fetches the GTFS data"""
    REQUESTS.inc()

    req = self.request()
    with urllib.request.urlopen(req) as f:
      out = f.read()
      RESPONSE_STATUS.labels(f.status).inc()

    RESPONSE_BYTES.observe(len(out))
    return out


class IrelandNTA(Fetcher):
  TEST_URL = "https://api.nationaltransport.ie/gtfsrtest/"
  PROD_URL = "https://api.nationaltransport.ie/gtfsr/v2/TripUpdates"

  def __init__(self, api_key: str, url: str):
    self.api_key = api_key
    self.url = url

  def request(self):
    headers = {
      "Cache-Control": "no-cache",
      "x-api-key": self.api_key,
    }
    return urllib.request.Request(self.url, None, headers)
  

class VicRoads(Fetcher):
  METROTRAIN_URL = "https://data-exchange-api.vicroads.vic.gov.au/opendata/v1/gtfsr/metrotrain-tripupdates"
  YARRATRAMS_URL = "https://data-exchange-api.vicroads.vic.gov.au/opendata/gtfsr/v1/tram/tripupdates"

  def __init__(self, api_key: str, url: str):
    self.api_key = api_key
    self.url = url

  def request(self):
    headers = {
      "Cache-Control": "no-cache",
      "Ocp-Apim-Subscription-Key": self.api_key,
      "User-Agent": "github.com/seanrees/gtfs-upcoming"      # endpoint does not like the Python UA
    }
    return urllib.request.Request(self.url, None, headers)
  

def MakeFetcher(provider: str, env: str, api_key: str) -> Fetcher:
  if provider == "nta":
    url = IrelandNTA.TEST_URL
    if env == 'prod':
      url = IrelandNTA.PROD_URL

    logging.info("Irish NTA, env=%s, url=%s", env, url)
    return IrelandNTA(api_key, url)
  elif provider == "vicroads":
    if env == 'metrotrain':
      url = VicRoads.METROTRAIN_URL
    elif env == 'tram':
      url = VicRoads.YARRATRAMS_URL
    else:
      logging.error("Unknown VicRoads/PTV env %s", env)
      return None
    
    logging.info("VicRoads/PTV, env=%s, url=%s", env, url)
    return VicRoads(api_key, url)
  
  return None