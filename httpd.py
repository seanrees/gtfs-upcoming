import logging
import http.server
import socketserver

from typing import Callable, Dict

class RequestHandler(http.server.BaseHTTPRequestHandler):
  # Override StreamRequestHandler.timeout; applies to the
  # request socket.
  timeout = 1

  def do_GET(self):
    h = self.server.Lookup(self.path)
    if h:
      h(self)
    else:
      self.Handle404()

  def Handle404(self):
    self.SendHeaders(200, 'text/html')

    html = self.GenerateHTMLHead('404 Not Found')
    html += f"<h1>404 Not Found</h1><p>Unknown path: {self.path}"
    html += self.GenerateHTMLFoot()

    self.Send(html)

  def SendHeaders(self, code: int, contentType: str='text/html') -> None:
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
