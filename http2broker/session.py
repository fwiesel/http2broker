import nghttp2
import logging
import asyncio
import sys
import os, time, io
from base64 import b64decode
from copy import copy, deepcopy
from .config import get_config
from datetime import timedelta, datetime
from uuid import uuid4 as uuid

from wheezy.template.engine import Engine
from wheezy.template.ext.core import CoreExtension
from wheezy.template.loader import FileLoader

from routes import Mapper
from importlib import import_module
import mimetypes

mimetypes.init()

LOG = logging.getLogger(__name__)

# Consider: https://docs.python.org/3/library/contextlib.html#contextlib.closing

template_engine = Engine(
    loader=FileLoader(get_config().get('templates', {}).get('search_path', 'content/templates-wheezy;content').split(';')),
    extensions=[CoreExtension()]
)

def last_modified(path):
    return (b'last-modified', time.strftime("%a, %d %b %Y %H:%M:%S %Z", time.gmtime(os.path.getmtime(path))))

def index(request, start_response):
    template = template_engine.get_template('index.html')
    if template:
        _status = None
        _headers = None

        def local_start(status, headers):
            nonlocal _status
            nonlocal _headers
            _status = status
            _headers.extend(headers)

        for path in []: # ['/static/app.js', '/static/app.css']:
            _status = 404
            _headers = copy(request.response['headers'])
            request.match['filename'] = path
            body = static_content(request, local_start)
            request.push(path, status=_status, headers=_headers, body=body)
        request._setup_session()
        start_response(200, [(b'content-type', 'text/html'), (b'cache-control', b'public, must-revalidate, max-age=60')])
        return template.render({'backends': get_config()})

def favicon(request, start_response):
    start_response(200, [(b'content-type', b'image-x-icon'), (b'cache-control', b'public, max-age=432000000'), last_modified(__file__)])
    return b64decode('iVBORw0KGgoAAAANSUhEUgAAABAAAAAQEAYAAABPYyMiAAAABmJLR0T///////8JWPfcAAAACXBIWXMAAABIAAAASABGyWs+AAAAF0lEQVRIx2NgGAWjYBSMglEwCkbBSAcACBAAAeaR9cIAAAAASUVORK5CYII=')


def not_found(request, start_response):
    start_response(404, [])
    return None

def static_content(request, start_response):
    local_path = "content%s" % request.match['filename']
    mimetype, _ = mimetypes.guess_type(local_path)
    start_response(200, [(b'content-type', mimetype), (b'cache-control', b'public, max-age=60'), last_modified(local_path)])
    f = io.open(local_path, 'rb', io.DEFAULT_BUFFER_SIZE)
    return f

class Request(nghttp2.BaseRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    # defined in BaseRequestHandler:
    #  scheme
    #  host

    @property
    def server_name(self):
        return self.host()

    @property
    def script_name(self):
        return ''

    @property
    def path_info(self):
        return self.path


def generate_routes():
    m = Mapper()
    m.connect('/', handler=index)
    m.connect('{filename:/static/.*?}', handler=static_content)
    m.connect('/favicon.ico', handler=favicon)
    for (k, config) in get_config().items():
        config = deepcopy(config)
        backend_module = config.pop('module')
        LOG.warn("Configuring %s", backend_module)
        module = import_module(backend_module)
        try:
            backend = module.create(config)
            for method in ['GET', 'PUT', 'POST', 'DELETE']:
                try:
                    m.connect("/q/%s" % k, conditions=dict(method=method), handler=getattr(backend, method.lower()))
                    m.connect("/q/%s/{pattern:.*?}" % k, conditions=dict(method=method), handler=getattr(backend, method.lower()))
                except AttributeError:
                    pass
        except AttributeError as e:
            LOG.error("Could not create controller for %s: %s", k, backend_module)
            LOG.error(e)
    return m

routes = generate_routes()

class Session(Request):
    SESSION_ID = 'SSID='
    backend = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_id = None
        self.response = {}
        self.match = None


    def get_backend(self, name):
        backend = Session.backend.get(name, None)
        if not backend:
            config = get_config().get(name, None)
            if not config:
                LOG.error("Cannot find config for '%s'", name)
                return None

            config = deepcopy(config)
            backend_module = config.pop('module')
            try:
                backend = getattr(sys.modules.get(backend_module, None), 'create')(config)
                Session.backend[name] = backend
            except AttributeError as e:
                LOG.error("Cannot load module %s for %s", backend_module, name)
                LOG.error(e)

        return backend


    def _get_session_cookie(self):
        cookies = [header[1] for header in self.headers if header[0].decode('ascii').lower() == 'cookie']

        for cookie in cookies:
            cookie = cookie.decode('ascii')
            for item in cookie.split('; '):
                if item.startswith(Session.SESSION_ID):
                    return cookie[len(Session.SESSION_ID)+1:].strip()
        return None

    def _setup_session(self):
        self.session_id = self._get_session_cookie() or str(uuid())
        self.response['headers'] = [('set-cookie', "%s=%s; Path=/; Expires=%s; Domain=%s" % (Session.SESSION_ID, self.session_id, (datetime.utcnow() + timedelta(hours=1)).strftime("%a, %d-%b-%Y %X UTC"), ''))]

    def start_response(self, status, headers):
        self.response['status'] = status
        self.response['headers'].extend(headers)

    def on_headers(self):
        self._setup_session()
        self.match = routes.match(self.path.decode('utf-8'))
        if self.match:
            self.response['body'] = self.match['handler'](self, self.start_response)

        return self.send_response(**self.response)

    def on_close(self, error_code):
        try:
            body = self.response.get('body', None)
            if body:
                if asyncio.iscoroutinefunction(body.close):
                    asyncio.async(body.close())
                else:
                    body.close()
        except AttributeError:
            pass
