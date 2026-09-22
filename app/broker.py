"""RabbitMQ plumbing: connect, declare the topology, publish safely.

This is where all six vocabulary words from the proposal actually appear:

  Producer    Publisher.publish()
  Exchange    declare_topology() creates the "orders" topic exchange
  Queue       declare_topology() creates payment / restaurant / notification
  Binding     queue_bind(), once per routing key
  Routing key config.RK_ORDER_CREATED and the workflow result keys
  Consumer    app/workers/base.py
"""
import json
import threading
import time

import pika

from app import config, logs

log = logs.setup("broker")


def connect(retries: int | None = None,
            delay: float | None = None) -> pika.BlockingConnection:
    """Open a connection, waiting while the broker finishes booting.

    RabbitMQ takes 10-20 seconds to accept connections after the container
    starts, and `docker compose up` returns long before that. Every process
    in this project waits instead of crashing.
    """
    retries = retries if retries is not None else config.CONNECT_RETRIES
    delay = delay if delay is not None else config.CONNECT_DELAY

    params = pika.URLParameters(config.AMQP_URL)
    params.heartbeat = config.HEARTBEAT
    params.blocked_connection_timeout = 30

    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return pika.BlockingConnection(params)
        except pika.exceptions.AMQPConnectionError as exc:
            last = exc
            log.warning(
                "broker not ready (%s/%s), retrying in %ss",
                attempt, retries, delay
            )
            time.sleep(delay)

    raise RuntimeError(
        f"could not reach RabbitMQ at {config.AMQP_URL}: {last}"
    )


def declare_topology(channel) -> None:
    """Create exchanges, queues and bindings. Safe to call repeatedly.

    Declaring is idempotent in RabbitMQ, so every process declares what it
    needs at startup and nothing depends on a setup script having been run in
    the right order.
    """
    # Dead-letter side first, so the main queues can point at it.
    channel.exchange_declare(
        config.DLX,
        exchange_type="fanout",
        durable=True
    )
    channel.queue_declare(config.DLQ, durable=True)
    channel.queue_bind(config.DLQ, config.DLX)

    # The main exchange: topic, so one publish can reach several queues.
    channel.exchange_declare(
        config.EXCHANGE,
        exchange_type=config.EXCHANGE_TYPE,
        durable=True
    )

    for queue, routing_keys in config.QUEUES.items():
        channel.queue_declare(
            queue,
            durable=True,
            arguments={"x-dead-letter-exchange": config.DLX},
        )

        for rk in routing_keys:
            channel.queue_bind(
                queue,
                config.EXCHANGE,
                routing_key=rk
            )


def message_properties(
    attempt: int = 1,
    original_rk: str | None = None,
    order_id: str = ""
) -> pika.BasicProperties:
    headers = {"x-attempt": attempt}

    if original_rk:
        headers["x-original-routing-key"] = original_rk

    return pika.BasicProperties(
        content_type="application/json",
        delivery_mode=2,
        message_id=str(order_id),
        timestamp=int(time.time()),
        headers=headers,
    )


class Publisher:
    """Thread-safe publisher with lazy reconnect, used by the API.

    pika channels are not thread-safe and FastAPI serves requests on a thread
    pool, so every publish takes a lock. At class-demo scale the lock costs
    nothing and it keeps the code honest.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._conn: pika.BlockingConnection | None = None
        self._ch = None

    def _ensure(self) -> None:
        if (self._conn is not None and self._conn.is_open
                and self._ch is not None and self._ch.is_open):
            return

        self._conn = connect()
        self._ch = self._conn.channel()
        declare_topology(self._ch)
        self._ch.confirm_delivery()

    def start(self) -> None:
        """Eagerly connect; used by the API lifespan startup check."""
        with self._lock:
            self._ensure()

    def publish(self, routing_key: str, payload: dict) -> None:
        body = json.dumps(payload).encode()

        with self._lock:
            for _ in range(2):
                try:
                    self._ensure()

                    confirmed = self._ch.basic_publish(
                        exchange=config.EXCHANGE,
                        routing_key=routing_key,
                        body=body,
                        properties=message_properties(
                            order_id=payload.get("order_id", "")
                        ),
                        mandatory=True,
                    )

                    if confirmed is False:
                        raise RuntimeError("broker negatively acknowledged publish")
                    return

                except (pika.exceptions.AMQPError, OSError) as exc:
                    log.warning(
                        "publish failed (%s), reconnecting",
                        exc
                    )
                    try:
                        if self._conn is not None and self._conn.is_open:
                            self._conn.close()
                    except Exception:
                        pass
                    self._conn = self._ch = None

            raise RuntimeError("publish failed twice")

    def healthy(self) -> bool:
        with self._lock:
            try:
                self._ensure()
                return bool(
                    self._conn and self._conn.is_open
                )
            except Exception:
                return False

    def close(self) -> None:
        with self._lock:
            if self._conn is not None and self._conn.is_open:
                self._conn.close()

            self._conn = self._ch = None
