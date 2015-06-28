rabbit: RABBITMQ_SERVER_START_ARGS="-eval error_logger:tty(true)." RABBITMQ_LOGS="-" /usr/local/sbin/rabbitmq-server
gnatsd: gnatsd -V -m 8081
redis: redis-server /usr/local/etc/redis.conf
server: PYTHONASYNCIODEBUG=1 src/h2a.py
