import nghttp2
import logging
import asyncio
import sys
from base64 import b64decode
from copy import deepcopy
from .config import get_config
from datetime import timedelta, datetime
from uuid import uuid4 as uuid

LOG = logging.getLogger(__name__)

# Consider: https://docs.python.org/3/library/contextlib.html#contextlib.closing


class Handler(nghttp2.BaseRequestHandler):
    FAVICON = ([('content-type', 'image-x-icon')], b64decode('iVBORw0KGgoAAAANSUhEUgAAABAAAAAQEAYAAABPYyMiAAAABmJLR0T///////8JWPfcAAAACXBIWXMAAABIAAAASABGyWs+AAAAF0lEQVRIx2NgGAWjYBSMglEwCkbBSAcACBAAAeaR9cIAAAAASUVORK5CYII='))
    backend = {}

    def get_backend(self, name):
        backend = Handler.backend.get(name, None)
        if not backend:
            config = get_config().get(name, None)
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
            cookies = [header[1] for header in self.headers if header[0].decode('ascii').lower() == 'cookie']
            LOG.debug("Cookies: %s", cookies)
            for cookie in cookies:
                cookie = cookie.decode('ascii')
                if cookie.startswith('SSID='):
                    session_id = cookie[5:-1]

            if session_id is None:
                session_id = uuid()

            LOG.debug(session_id)
            path  = self.path.decode('utf-8')
            parts = path.split('/', 3)
            backend = self.get_backend(parts[1])

            if backend is None:
                return self.not_found()

            self.body = backend(self, session_id)

            if self.body is None:
                return self.not_found()

            self.send_response(status=200,
                   headers=[('content-type', 'text/event-stream'), ('cache-control', 'no-cache'), ('set-cookie', "SSID=%s; Path=/; Expires=%s; Domain=%s" % (session_id, (datetime.now() + timedelta(hours=1)).strftime("%a, %d-%b-%Y %X %Z"), 'localhost'))],
                   body=self.body)

    def on_close(self, error_code):
        body = None
        try:
            body = self.body
        except AttributeError:
            pass

        if body:
            asyncio.async(self.body.close())
