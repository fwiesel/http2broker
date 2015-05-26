import nghttp2
import logging
import asyncio

from .body import Body

LOG = logging.getLogger(__name__)

# Consider: https://docs.python.org/3/library/contextlib.html#contextlib.closing

class Handler(nghttp2.BaseRequestHandler):

    def on_headers(self):
        if self.path == '/favicon.ico':
            return self.send_response(status=404, headers=[], body=None)
        else:
            self.body = Body(self)
            self.send_response(status=200,
                               headers=[('content-type', 'text/event-stream'), ('cache-control', 'no-cache')],
                               body=self.body)

    def on_close(self, error_code):
        LOG.debug("Goodbye")
        if self.body:
            asyncio.async(self.body.close())
