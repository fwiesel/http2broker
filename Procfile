rabbit: RABBITMQ_SERVER_START_ARGS="-eval error_logger:tty(true)." RABBITMQ_LOGS="-" /usr/local/sbin/rabbitmq-server
redis: redis-server /usr/local/etc/redis.conf
server: PYTHONASYNCIODEBUG=1 ./h2a.py
