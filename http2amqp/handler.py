import nghttp2
import logging
import asyncio
import sys
from base64 import b64decode
from copy import deepcopy

LOG = logging.getLogger(__name__)

# Consider: https://docs.python.org/3/library/contextlib.html#contextlib.closing


class Handler(nghttp2.BaseRequestHandler):
    FAVICON = ([('content-type', 'image-x-icon')], b64decode('iVBORw0KGgoAAAANSUhEUgAAABAAAAAQEAYAAABPYyMiAAAABmJLR0T///////8JWPfcAAAACXBIWXMAAABIAAAASABGyWs+AAAAF0lEQVRIx2NgGAWjYBSMglEwCkbBSAcACBAAAeaR9cIAAAAASUVORK5CYII='))
    CONFIG =  {
        'test' : {
            'type': 'amqp',
            'host': 'localhost',
            'port': 5672,
            'username': 'guest',
            'password': 'guest',
            'virtual_host': '/',
            'exchange_name': 'test.exchange',
            'exchange_type': 'topic'
        }
    }
    backend = {}

    def get_backend(self, name):
        backend = Handler.backend.get(name, None)
        if not backend:
            config = Handler.CONFIG.get(name, None)
            if not config:
                LOG.error("Cannot find config for %s", name)
                return None

            config = deepcopy(config)
            type = config.pop('type')

            backend_module = '.'.join(['http2amqp.backend', type])
            try:
                backend = getattr(sys.modules.get(backend_module, None), 'create')(config)
                Handler.backend[name] = backend
            except AttributeError as e:
                LOG.error("Cannot load module %s for %s", backend_module, name)
                LOG.error(e)

        return backend

    def not_found(self):
        return self.send_response(status=404, headers=[], body=None)

    def on_headers(self):
        self.body = None
        if self.path == '/':
            return self.send_response(status=200, headers=[], body=None)
        if self.path == '/favicon.ico':
            return self.send_response(status=200, headers=Handler.FAVICON[0], body=Handler.FAVICON[1])
        else:
            path  = self.path.decode('utf-8')
            parts = path.split('/', 3)
            backend = self.get_backend(parts[1])

            if backend is None:
                return self.not_found()

            self.body = backend(self)

            if self.body is None:
                return self.not_found()

            self.send_response(status=200,
                   headers=[('content-type', 'text/event-stream'), ('cache-control', 'no-cache')],
                   body=self.body)

    def on_close(self, error_code):
        if self.body:
            asyncio.async(self.body.close())
