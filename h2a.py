#!/usr/bin/env python3.4
# -*- coding: utf-8 -*-
import sys
sys.path.append('.')

import ssl
import logging
from http2broker.request import Request
import nghttp2

LOG = logging.getLogger('http2broker')


def main():
    logging.basicConfig(level=logging.WARNING)
    LOG.setLevel(logging.DEBUG)

    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH, cafile='demoCA/cacert.crt')
    ctx.load_cert_chain('server.crt', 'server.key')

    if ctx.cert_store_stats()['x509_ca'] < 1:
        LOG.warning('Do not have any CAs, client certificate will not work')

    ctx.verify_mode = ssl.CERT_OPTIONAL

    server = nghttp2.HTTP2Server(('127.0.0.1', 8443), Request, ssl=ctx)
    server.serve_forever()


if __name__ == "__main__":
    main()
