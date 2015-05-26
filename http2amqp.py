#!/usr/bin/env python3.4
# -*- coding: utf-8 -*-
import sys
sys.path.append('.')

import asynqp
import asyncio
import ssl
import io
import logging
import nghttp2
from collections import deque

LOG = logging.getLogger('http2amqp')

# Consider: https://docs.python.org/3/library/contextlib.html#contextlib.closing


class Body:
    def __init__(self, handler):
        self.handler = handler
        self.handler.eof = False
        self.buf = deque()
        LOG.debug("Init")
        asyncio.async(self.read_amqp())

    def __call__(self, n):
        data = self.buf.popleft() if len(self.buf) > 0 else None
        if not data and not self.handler.eof:
            LOG.debug("Body, no data")
            return None, nghttp2.DATA_DEFERRED
        else:
            LOG.debug("Body, with data %d", len(data))
            return data, nghttp2.DATA_EOF if self.handler.eof else nghttp2.DATA_OK

    @asyncio.coroutine
    def read_amqp(self):
        self.connection, self.channel = yield from asynqp.connect_and_open_channel(host='localhost', port=5672, username='guest', password='guest', virtual_host='/')
        self.exchange = yield from self.channel.declare_exchange('test.exchange', 'topic', durable=False, auto_delete=True)
        self.queue = yield from self.channel.declare_queue('test.queue', durable=False, auto_delete=True)
        yield from self.queue.bind(self.exchange, '#')
        yield from self.queue.consume(self.consume)

        # if not channel is None:
        #       yield from channel.close()
        #    if not connection is None:
        #        yield from connection.close()

    def consume(self, message):
        LOG.debug(message.body)
        self.buf.append(message.body)
        self.handler.resume()
        message.ack()


class Handler(nghttp2.BaseRequestHandler):
    def on_headers(self):
        LOG.debug("Hello")
        body = Body(self)
        self.send_response(status=200,
                           headers=[('content-type', 'text/plain')],
                           body=body)

    def on_close(self, error_code):
        LOG.debug("Goodbye")

def main():
    logging.basicConfig(level=logging.INFO)
    LOG.setLevel(logging.DEBUG)
    ctx = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
    ctx.options = ssl.OP_ALL | ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3
    ctx.load_cert_chain('server.crt', 'server.key')
    server = nghttp2.HTTP2Server(('127.0.0.1', 8443), Handler, ssl=ctx)
    server.serve_forever()


if __name__ == "__main__":
    main()
