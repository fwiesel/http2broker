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


class Request(nghttp2.BaseRequestHandler):
    SESSION_ID = 'SSID='
    FAVICON    = ([('content-type', 'image-x-icon')], b64decode('iVBORw0KGgoAAAANSUhEUgAAABAAAAAQEAYAAABPYyMiAAAABmJLR0T///////8JWPfcAAAACXBIWXMAAABIAAAASABGyWs+AAAAF0lEQVRIx2NgGAWjYBSMglEwCkbBSAcACBAAAeaR9cIAAAAASUVORK5CYII='))
    backend    = {}


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_id = None
        self.response_status = 404
        self.response_headers = []
        self.response_body = None

    def get_backend(self, name):
        backend = Request.backend.get(name, None)
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
                Request.backend[name] = backend
            except AttributeError as e:
                LOG.error("Cannot load module %s for %s", backend_module, name)
                LOG.error(e)

        return backend


    def _get_session_cookie(self):
        cookies = [header[1] for header in self.headers if header[0].decode('ascii').lower() == 'cookie']

        for cookie in cookies:
            cookie = cookie.decode('ascii')
            for item in cookie.split('; '):
                if item.startswith(Request.SESSION_ID):
                    return cookie[len(Request.SESSION_ID)+1:].strip()
        return None

    def _setup_session(self):
        self.session_id = self._get_session_cookie() or str(uuid())
        self.response_headers.extend([('set-cookie', "%s=%s; Path=/; Expires=%s; Domain=%s" % (Request.SESSION_ID, self.session_id, (datetime.utcnow() + timedelta(hours=1)).strftime("%a, %d-%b-%Y %X UTC"), ''))])

    def on_headers(self):
        self._setup_session()

        if self.path == '/':
            self.response_status = 200
        if self.path == '/favicon.ico':
            self.response_status = 200
            self.response_headers.extend(Request.FAVICON[0])
        else:
            path  = self.path.decode('utf-8')
            parts = path.split('/', 3)
            backend = self.get_backend(parts[1])

            if backend:
                self.response_body = backend(self)
            if self.response_body:
                self.response_status = 200
                self.response_headers.extend([('content-type', 'text/event-stream'), ('cache-control', 'no-cache')])

        return self.send_response(status=self.response_status, headers=self.response_headers, body=self.response_body)

    def on_close(self, error_code):
        body = None
        try:
            body = self.response_body
        except AttributeError:
            pass

        if body:
            asyncio.async(body.close())
