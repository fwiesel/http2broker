from collections import deque
import logging
import nghttp2
import asynqp
import asyncio
import urllib

LOG = logging.getLogger(__name__)


def create(config):
    return Client(config)

class Client:
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

    def __call__(self, request):
        return Channel(self, request)

class Channel:
    def __init__(self, client, request):
        self.client = client
        self.request = request
        self.request.eof = False
        self.buf = deque()
        self.channel = None
        self.queue = None
        self.exchange = None
        asyncio.async(self.read_amqp())

    @staticmethod
    def message_proc(msg):
        data = msg.body
        msg.ack
        return data

    def __call__(self, n):
        items = len(self.buf)
        message = self.buf.popleft() if items > 0 else None

        if not message and not self.request.eof:
            return None, nghttp2.DATA_DEFERRED
        else:
            if items > 1:
                self.request.resume()
            message.ack()
            return message.body, nghttp2.DATA_EOF if self.request.eof else nghttp2.DATA_OK

    @asyncio.coroutine
    def read_amqp(self):
        self.channel = yield from self.client.open_channel()

        exchange_type = self.client.config.get('exchange_type', 'topic')
        self.exchange = yield from self.channel.declare_exchange(self.client.config.get('exchange_name', "amq.%s" % exchange_type), exchange_type, durable=False, auto_delete=True)
        self.queue = yield from self.channel.declare_queue(str(self.request.session_id), durable=False, auto_delete=True) # , arguments={'x-expires': 300})

        path = self.request.path.decode('utf-8').split('/', 2)
        pattern = urllib.parse.unquote(path[-1]) if len(path) == 3 else '#'
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


