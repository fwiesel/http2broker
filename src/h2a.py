#!/usr/bin/env python3.4
# -*- coding: utf-8 -*-
import sys
sys.path.append('.')

import ssl
import logging
from http2broker.session import Session
from http2broker.config import get_config
import nghttp2

LOG = logging.getLogger('http2broker')


def main():
    logging.basicConfig(level=logging.WARNING)
    LOG.setLevel(logging.DEBUG)

    config = {
        'cafile': 'cacert.crt',
        'certfile': 'server.crt',
        'keyfile': 'server.key',
        'host': None,
        'port': 443
    }
    config.update(get_config().get('h2a', {}))

    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH, cafile=config['cafile'])
    ctx.load_cert_chain(config['certfile'], config['keyfile'])

    if ctx.cert_store_stats()['x509_ca'] < 1:
        LOG.warning('Do not have any CAs, client certificate will not work')

    ctx.verify_mode = ssl.CERT_OPTIONAL

    server = nghttp2.HTTP2Server((config['host'], int(config['port'])), Session, ssl=ctx)
    server.serve_forever()


if __name__ == "__main__":
    main()
