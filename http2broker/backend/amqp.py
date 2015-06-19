from collections import deque
import logging
import nghttp2
import asynqp
import asyncio
import urllib
import io
from fnmatch import fnmatch

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
        if fnmatch(TextEventStream.content_type(), media_range):
            return TextEventStream
        elif fnmatch(PlainTextStream.content_type(), media_range):
            return PlainTextStream



class Controller:
    def __init__(self, config):
        self._config = config
        self._connection = None

    @property
    def config(self):
        return self._config

    @asyncio.coroutine
    def open_channel(self):
        if not self._connection is None:
            channel = yield from self._connection.open_channel()
        else:
            LOG.debug("Connecting to %s", self._config)
            self._connection, channel = yield from asynqp.connect_and_open_channel(host=self._config['host'],
                                                                                   username=self._config['username'],
                                                                                   password=self._config['password'],
                                                                                   virtual_host=self._config['virtual_host'])

        return channel

    def get(self, request, start_response):
        accept = next(i for i in request.headers if i[0] == b'accept')
        accept = accept[1] if not accept is None else b'text/event-stream'
        serialiser = create_serialiser(accept)

        start_response(200, [('content-type', serialiser.content_type()), ('cache-control', 'no-cache')])
        return Channel(self, request, serialiser)

class Channel:
    def __init__(self, client, request, serialiser):
        self.client = client
        self.request = request
        self.serialiser = serialiser
        self.request.eof = False
        self.buf = deque()
        self.channel = None
        self.queue = None
        self.exchange = None
        asyncio.async(self.read_amqp())

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
    def read_amqp(self):
        self.channel = yield from self.client.open_channel()

        exchange_type = self.client.config.get('exchange_type', 'topic')
        self.exchange = yield from self.channel.declare_exchange(self.client.config.get('exchange_name', "amq.%s" % exchange_type), exchange_type, durable=False, auto_delete=False, arguments={})
        self.queue = yield from self.channel.declare_queue(str(self.request.session_id), durable=False, auto_delete=False, arguments={'x-expires': 5*60*1000})

        pattern = urllib.parse.unquote(self.request.match.get('pattern', '#'))
        LOG.debug('Subscribing to %s', pattern)

        yield from self.queue.bind(self.exchange, pattern)
        yield from self.queue.consume(self.consume)

    def consume(self, message):
        self.buf.append(message)
        self.request.resume()

    @asyncio.coroutine
    def close(self):
        if not self.channel is None:
           yield from self.channel.close()


