import http.server
import logging
import socket
import threading
import urllib.parse
from collections.abc import Callable

import prometheus_client  # type: ignore[import]
from opentelemetry import trace

logger = logging.getLogger(__name__)


# Metrics
REQUEST_COUNT = prometheus_client.Counter(
  'gtfs_http_requests_total',
  'Requests to the internal webserver',
  ['path'])

RESPONSE_STATUS = prometheus_client.Counter(
  'gtfs_http_response_status_codes',
  'HTTP response codes from the internal webserver',
  ['code'])

UNKNOWN_PATH_COUNT = prometheus_client.Counter(
  'gtfs_http_unknown_paths_total',
  'Requests to unknown paths in the internal webserver')

tracer = trace.get_tracer("tracer.httpd")

# server.address str
# server.port int
# client.address
# client.port
# thread.name str threading.current_thread().name
# thread.id int threading.current_thread().ident


class RequestHandler(http.server.BaseHTTPRequestHandler):
  # Override StreamRequestHandler.timeout; applies to the
  # request socket.
  timeout = 5

  @tracer.start_as_current_span("do_GET", kind=trace.SpanKind.SERVER)
  def do_GET(self):
    pr = urllib.parse.urlparse(self.path)
    path = pr.path
    self.params = urllib.parse.parse_qs(pr.query)

    current_span = trace.get_current_span()
    current_span.set_attributes({
      'server.address': socket.gethostname(),
      'server.port': self.server.server_address[1],
      'client.address': self.client_address[0],
      'client.port': self.client_address[1],
      'thread.name': threading.current_thread().name,
      'thread.id': threading.current_thread().ident,
      'http.request.method': 'GET',
      'url.path': self.path,
      'user_agent.original': self.headers.get('User-Agent', '')
    })

    h = self.server.Lookup(path)
    if h:
      try:
        h(self)
      except Exception as ex:
        current_span.set_attribute("error.type", str(ex))
        logger.exception("error processing %s", path)
        self.SendISE(ex)

      REQUEST_COUNT.labels(self.path).inc()
    else:
      self.Handle404()
      UNKNOWN_PATH_COUNT.inc()

  def Handle404(self):
    self.SendHeaders(404, 'text/html')

    html = self.GenerateHTMLHead('404 Not Found')
    html += f"<h1>404 Not Found</h1><p>Unknown path: {self.path}"
    html += self.GenerateHTMLFoot()

    self.Send(html)

  def SendISE(self, ex):
    self.SendHeaders(500, 'text/html')

    html = self.GenerateHTMLHead('500 Internal Server Error')
    html += f"<h1>500 Internal Server Error</h1><p>Exception: {ex}"
    html += self.GenerateHTMLFoot()

    self.Send(html)

  def SendHeaders(self, code: int, contentType: str='text/html') -> None:
    self._response_code = code
    self._response_content_type = contentType


  def Send(self, out: str) -> None:
    RESPONSE_STATUS.labels(self._response_code).inc()
    self.send_response(self._response_code)
    self.send_header('Content-type', self._response_content_type)

    current_span = trace.get_current_span()
    current_span.set_attribute('http.response.status_code', self._response_code)

    self.end_headers()
    self.flush_headers()

    self.wfile.write(bytes(out, 'utf-8'))

  def GenerateHTMLHead(self, title: str) -> str:
    return f"""<!doctype html>
<html itemscope="" itemtype="http://schema.org/WebPage" lang="en-IE">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
</head>
<body>
"""

  def GenerateHTMLFoot(self) -> str:
    return "</body></html>"


class HTTPServer(http.server.HTTPServer):
  def __init__(self, port: int=6824):
    super().__init__(('', port), RequestHandler)
    self._handlers : dict[str, Callable[[RequestHandler], None]] = {}

  def Register(self, path: str, handler: Callable[[RequestHandler], None]):
    self._handlers[path] = handler

  def Lookup(self, path: str):
    return self._handlers.get(path, None)
