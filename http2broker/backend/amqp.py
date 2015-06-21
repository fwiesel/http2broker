from collections import deque
import logging
import nghttp2
import asynqp
import asyncio
import urllib
import io
from fnmatch import fnmatch
from urllib.parse import urlparse, parse_qs

LOG = logging.getLogger(__name__)


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
        body_in = io.BytesIO(message.body)
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
        return b''.join([message.body, b"\n"])


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
        self._connection = None
        self._channel = None
        self._exchange = None
        self.setup_done = asyncio.async(self.setup())

    @asyncio.coroutine
    def setup(self):
        LOG.debug("Connecting to %s", self._config)
        self._connection = yield from asynqp.connect(host=self._config['host'],
                                                     username=self._config['username'],
                                                     password=self._config['password'],
                                                     virtual_host=self._config['virtual_host'])
        self._channel = yield from self._connection.open_channel()
        exchange_type = self._config.get('exchange_type', 'topic')
        self._exchange = yield from self._channel.declare_exchange(self._config.get('exchange_name', "amq.{}".format(exchange_type)),
                                                                   exchange_type, durable=False, auto_delete=False)

    @property
    def config(self):
        return self._config

    @property
    def connection(self):
        return self._connection

    @property
    def channel(self):
        return self._channel

    @property
    def exchange(self):
        return self._exchange

    def subscribe(self, request, serialiser):
        return Subscription(self, request, serialiser)

    def publish(self, request, start_response):
        return Sender(self, request, start_response)

class Subscription(object):
    def __init__(self, session, request, serialiser):
        self.session = session
        self.request = request
        self.serialiser = serialiser
        self.request.eof = False
        self.buf = deque()
        self.queue = None
        self.binding = None
        self.consumer = None
        asyncio.async(self.setup())

    def __call__(self, n):
        items = len(self.buf)
        message = self.buf.popleft() if items > 0 else None

        if not message and not self.request.eof:
            return None, nghttp2.DATA_DEFERRED
        else:
            if items > 1:
                self.request.resume()
            data = self.serialiser.serialise(message)
            message.ack()
            return data, nghttp2.DATA_EOF if self.request.eof else nghttp2.DATA_OK

    @asyncio.coroutine
    def setup(self):
        yield from self.session.setup_done
        self.queue = yield from self.session.channel.declare_queue(str(self.request.session_id), durable=False, auto_delete=False, arguments={'x-expires': 5*60*1000})

        pattern = urllib.parse.unquote(self.request.match.get('pattern', '#'))
        LOG.debug('Subscribing to %s', pattern)
        self.binding = yield from self.queue.bind(self.session.exchange, pattern)
        self.consumer = yield from self.queue.consume(self.consume)

    def consume(self, message):
        self.buf.append(message)
        self.request.resume()

    @asyncio.coroutine
    def close(self):
        if not self.binding is None:
            yield from self.binding.unbind()
        if not self.consumer is None:
            yield from self.consumer.cancel()
        if not self.queue is None:
            yield from self.queue.delete(if_unused=False, if_empty=False)

    def on_request_done(self):
        pass


class Sender(object):
    def __init__(self, session, request, start_response):
        self.start_response = start_response
        self.session = session
        self.request = request
        self.response = None
        self.data = io.BytesIO()

    def __call__(self, n):
        if self.response is None:
            return None, nghttp2.DATA_DEFERRED
        else:
            return self.response, nghttp2.DATA_EOF

    @asyncio.coroutine
    def publish(self):
        yield from self.session.setup_done
        params = parse_qs(urlparse(self.request.path).query)
        data = self.data.getvalue()
        try:
            content_type = next(i for i in self.request.headers if i[0] == b'content-type')
            if content_type:
                content_type = content_type[1]
            else:
                content_type = 'text/plain'
            message = asynqp.Message(data, content_type=content_type)
            key = self.session.config.get('routing_key', params.get(b'k', ['default'])[0])
            self.session.exchange.publish(message, key, mandatory=False)
            self.start_response(200, [('content-type', 'application/json'), ('cache-control', 'no-cache')])
            self.response = b'{}'
            self.request.resume()
        except KeyError as e:
            self.start_response(500, [('content-type', 'application/json'), ('cache-control', 'no-cache')])
            self.response = "{'e': {} }".format(e)
            self.request.resume()

    def on_data(self, data):
        self.data.write(data)

    def on_request_done(self):
        asyncio.async(self.publish())

