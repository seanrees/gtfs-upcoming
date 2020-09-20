import logging
import http.server
import urllib.parse
import socketserver

from typing import Callable, Dict

import prometheus_client    # type: ignore[import]


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


class RequestHandler(http.server.BaseHTTPRequestHandler):
  # Override StreamRequestHandler.timeout; applies to the
  # request socket.
  timeout = 5

  def do_GET(self):
    pr = urllib.parse.urlparse(self.path)
    path = pr.path
    self.params = urllib.parse.parse_qs(pr.query)

    h = self.server.Lookup(path)
    if h:
      h(self)
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

  def SendHeaders(self, code: int, contentType: str='text/html') -> None:
    RESPONSE_STATUS.labels(code).inc()

    self.send_response(code)
    self.send_header('Content-type', contentType)
    self.end_headers()

  def Send(self, out: str) -> None:
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
    self._handlers : Dict[str, Callable[[RequestHandler], None]] = {}

  def Register(self, path: str, handler: Callable[[RequestHandler], None]):
    self._handlers[path] = handler

  def Lookup(self, path: str):
    return self._handlers.get(path, None)
