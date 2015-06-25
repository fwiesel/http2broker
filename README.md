# http2broker
A broker from HTTP2 to various pub/sub messaging systems

The `GET` request will be interpreted as a subscribe, which currently results in an `text/event-stream` output, while a `POST` publishes a message on a topic to a routing key.

It is based on asyncio, so python 3.4 is a minimum requirement as of now.
The HTTP2 server is provided through the python bindings of (nghttp2)[https://nghttp2.org/], which has to be installed manually.
All other dependencies should be in the `requirements.txt`.

Currently, AMQP / MQTT and Redis pub-sub works in a limited way.
No rigorous testing has been done, but it works for me in a Chrome browser.
