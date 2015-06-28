from collections import deque
import logging
import nghttp2
import urllib
from urllib.parse import urlparse, parse_qs
import io
import asyncio
import pynats

LOG = logging.getLogger(__name__)
loop = asyncio.get_event_loop()

def _topic_translation(key, translation=str.maketrans('/#', '.>')):
    return key.translate(translation)


def create(config):
    return Controller(config)

class Serialiser(object):
    pass

class TextEventStream(Serialiser):
    @staticmethod
    def content_type():
        return 'text/event-stream'

    @staticmethod
    def serialise(message):
        body_in = io.BytesIO(message.data)
        out = bytearray()
        for line in body_in:
            out.extend(b'data: ')
            out.extend(line)
            out.extend(b"\n")
        out.extend(b"\n")
        return out

class PlainTextStream(Serialiser):
    @staticmethod
    def content_type():
        return 'text/plain'

    @staticmethod
    def serialise(message):
        return b''.join([message.payload, b"\n"])


def create_serialiser(accept_string):
    media_ranges = { media_range: { key: value for key, value in map(lambda x: x.split('=', 1), param_list) } for media_range, *param_list in map(lambda x: map(lambda y: y.strip(), x.split(';')), accept_string.decode('ascii').split(',')) }

    for media_range, _ in sorted(media_ranges.items(), key=lambda x: float(x[1].get('q', 1.0)), reverse=True):
        # if fnmatch(TextEventStream.content_type(), media_range):
        return TextEventStream
        #elif fnmatch(PlainTextStream.content_type(), media_range):
        #    return PlainTextStream



class Controller(object):
    def __init__(self, config):
        self._config = config
        self._sessions = {}

    @property
    def config(self):
        return self._config

    def session(self, request):
        try:
            return self._sessions[request.session_id]
        except KeyError:
            session = Session(self.config, request)
            self._sessions[request.session_id] = session
            return session

    def post(self, request, start_response):
        return self.session(request).publish(request, start_response)

    def get(self, request, start_response):
        accept = next(i for i in request.headers if i[0] == b'accept')
        accept = accept[1] if not accept is None else b'text/event-stream'
        serialiser = create_serialiser(accept)

        start_response(200, [('content-type', serialiser.content_type()), ('cache-control', 'no-cache')])
        return self.session(request).subscribe(request, serialiser)


class Session(object):
    def __init__(self, config, request):
        self._config = config
        self._client = pynats.Connection(config['url'], request.session_id, config.get('ssl_required', False))
        self._subscriptions = []
        self._stop = False
        self.setup_done = asyncio.async(self.setup())

    @asyncio.coroutine
    def setup(self):
        LOG.debug("Connecting to %s", self._config)
        yield from self._client.connect()

    @property
    def config(self):
        return self._config

    @property
    def client(self):
        return self._client

    def subscribe(self, request, serialiser):
        subscription = Subscription(self, request, serialiser)
        self._subscriptions.append(subscription)
        asyncio.async(subscription.subscribe())
        return subscription

    def publish(self, request, start_response):
        return Sender(self, request, start_response)


class Subscription(object):
    def __init__(self, session, request, serialiser):
        self.session = session
        self.request = request
        self.serialiser = serialiser
        self.request.eof = False
        self.buf = deque()

    def __call__(self, n):
        items = len(self.buf)
        message = self.buf.popleft() if items > 0 else None

        if not message and not self.request.eof:
            return None, nghttp2.DATA_DEFERRED
        else:
            if items > 1:
                self.request.resume()
            data = self.serialiser.serialise(message)
            return data, nghttp2.DATA_EOF if self.request.eof else nghttp2.DATA_OK

    @asyncio.coroutine
    def subscribe(self):
        yield from self.session.setup_done
        subscription = _topic_translation(self.session.config.get('subscription', urllib.parse.unquote(self.request.match.get('subscription', '#'))))
        self.session.client.subscribe(subscription, self.consume, self.request.session_id)

    def consume(self, message):
        self.buf.append(message)
        self.request.resume()

    def on_request_done(self):
        pass

class Sender(object):
    def __init__(self, session, request, start_response):
        self.start_response = start_response
        self.session = session
        self.request = request
        self.data = io.BytesIO()
        self.response = None

    def __call__(self, n):
        if self.response is None:
            return None, nghttp2.DATA_DEFERRED
        else:
            return self.response, nghttp2.DATA_EOF

    def on_data(self, data):
        self.data.write(data)

    @asyncio.coroutine
    def _publish(self, key, payload):
        yield from self.session.setup_done
        self.session.client.publish(key, payload)
        self.start_response(200, [('content-type', 'application/json'), ('cache-control', 'no-cache')])
        self.response = b'{}'
        self.request.resume()

    def on_request_done(self):
        params = parse_qs(urlparse(self.request.path).query)
        self.data.seek(0)
        with io.TextIOWrapper(self.data, write_through=True) as ios:
            payload = ios.read()
        try:
            key = self.session.config.get('publish_topic', params.get(b'k', ['default'])[0])
            asyncio.async(self._publish(key, payload))
        except KeyError as e:
            self.start_response(500, [('content-type', 'application/json'), ('cache-control', 'no-cache')])
            self.response = "{'e': {} }".format(e)
            self.request.resume()

