#!/usr/bin/env python3.4
# -*- coding: utf-8 -*-
import sys
sys.path.append('.')

import ssl
import logging
from http2amqp.handler import Handler
import nghttp2

LOG = logging.getLogger('http2amqp')

def main():
    logging.basicConfig(level=logging.WARNING)
    LOG.setLevel(logging.DEBUG)
    ctx = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
    ctx.options = ssl.OP_ALL | ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3
    ctx.load_cert_chain('server.crt', 'server.key')
    server = nghttp2.HTTP2Server(('127.0.0.1', 8443), Handler, ssl=ctx)
    server.serve_forever()


if __name__ == "__main__":
    main()
