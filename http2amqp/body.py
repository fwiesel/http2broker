from collections import deque
import logging
import nghttp2
import asynqp
import asyncio

LOG = logging.getLogger(__name__)


class Body:
    def __init__(self, handler):
        self.handler = handler
        self.handler.eof = False
        self.buf = deque()
        asyncio.async(self.read_amqp())

    @staticmethod
    def message_proc(msg):
        data = msg.body
        msg.ack
        return data

    def __call__(self, n):
        items = len(self.buf)
        message = self.buf.popleft() if items > 0 else None

        if not message and not self.handler.eof:
            return None, nghttp2.DATA_DEFERRED
        else:
            if items > 1:
                self.handler.resume()
            message.ack()
            return message.body, nghttp2.DATA_EOF if self.handler.eof else nghttp2.DATA_OK

    @asyncio.coroutine
    def read_amqp(self):
        self.connection, self.channel = yield from asynqp.connect_and_open_channel(host='localhost', port=5672, username='guest', password='guest', virtual_host='/')
        self.exchange = yield from self.channel.declare_exchange('test.exchange', 'topic', durable=False, auto_delete=True)
        self.queue = yield from self.channel.declare_queue('test.queue', durable=False, auto_delete=True)
        yield from self.queue.bind(self.exchange, '#')
        yield from self.queue.consume(self.consume)

    def consume(self, message):
        self.buf.append(message)
        self.handler.resume()

    @asyncio.coroutine
    def close(self):
        if not self.channel is None:
           yield from self.channel.close()
        if not self.connection is None:
            yield from self.connection.close()


