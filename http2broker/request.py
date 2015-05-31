import nghttp2
import logging
import asyncio
import sys
from base64 import b64decode
from copy import deepcopy
from .config import get_config
from datetime import timedelta, datetime
from uuid import uuid4 as uuid

from wheezy.template.engine import Engine
from wheezy.template.ext.core import CoreExtension
from wheezy.template.loader import FileLoader


LOG = logging.getLogger(__name__)

# Consider: https://docs.python.org/3/library/contextlib.html#contextlib.closing

template_engine = Engine(
    loader=FileLoader(get_config().get('templates', {}).get('search_path', 'content/templates-wheezy;content').split(';')),
    extensions=[CoreExtension()]
)

class Request(nghttp2.BaseRequestHandler):
    SESSION_ID = 'SSID='
    FAVICON    = { 'status': 200, 'headers': [('content-type', 'image-x-icon'), ('cache-control', 'public')], 'body': b64decode('iVBORw0KGgoAAAANSUhEUgAAABAAAAAQEAYAAABPYyMiAAAABmJLR0T///////8JWPfcAAAACXBIWXMAAABIAAAASABGyWs+AAAAF0lEQVRIx2NgGAWjYBSMglEwCkbBSAcACBAAAeaR9cIAAAAASUVORK5CYII=') }
    NOT_FOUND  = { 'status': 404, 'header': [], 'body': None }
    backend    = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_id = None
        self.response = {}


    def get_backend(self, name):
        backend = Request.backend.get(name, None)
        if not backend:
            config = get_config().get(name, None)
            if not config:
                LOG.error("Cannot find config for '%s'", name)
                return None

            config = deepcopy(config)
            type = config.pop('type')

            backend_module = '.'.join(['http2broker.backend', type])
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
        self.response = { 'headers':  [('set-cookie', "%s=%s; Path=/; Expires=%s; Domain=%s" % (Request.SESSION_ID, self.session_id, (datetime.utcnow() + timedelta(hours=1)).strftime("%a, %d-%b-%Y %X UTC"), ''))] }

    def on_headers(self):
        self.path = self.path.decode('utf-8')

        if self.path is None or self.path == '' or self.path == '/':
            template = template_engine.get_template('index.html')
            if template:
                self._setup_session()
                self.response['status'] = 200
                self.response['headers'].extend([('content-type', 'text/html'), ('cache-control', 'public')])
                self.response['body'] = template.render({'backends': get_config()})
        elif self.path == '/favicon.ico':
            self.response = Request.FAVICON
        elif self.path.startswith('/static/'):
            with open("content%s" % self.path, 'r') as f:
                self.response = { 'status': 200,
                                  'headers': [('content-type', 'text/javascript'), ('cache-control', 'public')],
                                  'body': f.read()
                                }
        else:
            parts = self.path.split('/', 3)
            backend = self.get_backend(parts[1])

            if backend:
                self._setup_session()
                body = backend(self)
                if body:
                    self.response['status'] = 200
                    self.response['headers'].extend([('content-type', 'text/event-stream'), ('cache-control', 'no-cache')])
                    self.response['body'] = body
                else:
                    self.response['status'] = 404

        return self.send_response(**(self.response or Request.NOT_FOUND))

    def on_close(self, error_code):
        body = None
        try:
            body = self.response['body']
            if body:
                if asyncio.iscoroutinefunction(body.close):
                    asyncio.async(body.close())
                else:
                    body.close()
        except AttributeError:
            pass
