#!/usr/bin/env python3.4
import asyncio, nghttp2, asynqp
import io, ssl


@asyncio.coroutine
def read_amqp(handler):
   self.amqp_connection, self.amqp_channel = asynqp.connect_and_open_channel(host='localhost', port=5672, username='guest', password='guest', virtual_host='/')
   
   yield from self.amqp_channel.close
   yield from self.amqp_connection.close


class Body:
    def __init__(self, handler):
        self.handler = handler
        self.handler.eof = False
        self.handler.buf = io.BytesIO()

    def generate(self, n):
        buf = self.handler.buf
        data = buf.read1(n)
        if not data and not self.handler.eof:
            return None, nghttp2.DATA_DEFERRED
        return data, nghttp2.DATA_EOF if self.handler.eof else nghttp2.DATA_OK

class Handler(nghttp2.BaseRequestHandler):
    def on_headers(self):
        body = Body(self)
        asyncio.async(read_amqp(self))
        self.send_response(status=200,
                           headers = [('content-type', 'text/plain')],
                           body=body)

    def on_close(self, error_code):
        print("Goodbye")

def main():
   ctx = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
   ctx.options = ssl.OP_ALL | ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3
   ctx.load_cert_chain('server.crt', 'server.key')
   server = nghttp2.HTTP2Server(('127.0.0.1', 8443), Handler, ssl=ctx)
   server.serve_forever()

if __name__ == "__main__":
    main()
