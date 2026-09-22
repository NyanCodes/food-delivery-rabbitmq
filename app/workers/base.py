"""Shared RabbitMQ consumer loop with acknowledgements, retry, and DLQ handling."""

import json
import os
import signal
from dataclasses import dataclass
from typing import Callable

from app import broker, config, db, logs, store


@dataclass
class Context:
    routing_key: str
    attempt: int
    worker: str
    log: object
    emit: Callable[[str, dict], None]


def run_worker(queue: str, handler, name: str | None = None) -> None:
    """Consume one delivery at a time and acknowledge only durable outcomes."""
    name = name or queue
    log = logs.setup(name)
    db.wait_for_db()
    connection = broker.connect()
    channel = connection.channel()
    broker.declare_topology(channel)
    channel.confirm_delivery()
    channel.basic_qos(prefetch_count=config.PREFETCH)

    def publish(exchange: str, routing_key: str, payload: dict, properties) -> None:
        confirmed = channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=json.dumps(payload).encode(),
            properties=properties,
            mandatory=True,
        )
        if confirmed is False:
            raise RuntimeError("broker negatively acknowledged publish")

    def emit(routing_key: str, payload: dict) -> None:
        publish(config.EXCHANGE, routing_key, payload,
                broker.message_properties(order_id=payload.get("order_id", "")))

    def retry(original_rk: str, payload: dict, attempt: int) -> None:
        # The default exchange routes by queue name, so only the failed service
        # receives this retry. Republishing order.created would duplicate work.
        publish(
            "", queue, payload,
            broker.message_properties(
                attempt=attempt,
                original_rk=original_rk,
                order_id=payload.get("order_id", ""),
            ),
        )

    def on_message(ch, method, props, body):
        payload = json.loads(body)
        order_id = payload.get("order_id", "unknown")
        headers = props.headers or {}
        attempt = int(headers.get("x-attempt", 1))
        routing_key = headers.get("x-original-routing-key") or method.routing_key
        ctx = Context(routing_key, attempt, name, log, emit)
        log.info("-> %s %s (attempt %s)", routing_key, order_id, attempt)

        try:
            handler(payload, ctx)
        except Exception as exc:
            log.error("!! %s failed: %s", order_id, exc)
            if attempt < config.MAX_RETRIES:
                try:
                    retry(routing_key, payload, attempt + 1)
                except Exception:
                    log.exception("retry publish failed; preserving original %s", order_id)
                    ch.basic_nack(method.delivery_tag, requeue=True)
                    return
                ch.basic_ack(method.delivery_tag)
                log.info("   requeued %s as attempt %s", order_id, attempt + 1)
            else:
                _store_failed(order_id, name, exc)
                ch.basic_nack(method.delivery_tag, requeue=False)
                log.error("   dead-lettered %s after %s attempts", order_id, attempt)
            return

        ch.basic_ack(method.delivery_tag)
        log.info("<- done %s", order_id)

    channel.basic_consume(queue=queue, on_message_callback=on_message)

    def shutdown(*_args):
        log.info("shutting down - unacknowledged messages remain queued")
        if channel.is_open:
            channel.stop_consuming()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    log.info("waiting on %s (pid %s, prefetch %s)",
             queue, os.getpid(), config.PREFETCH)
    try:
        channel.start_consuming()
    finally:
        if connection.is_open:
            connection.close()
        db.close()


def _store_failed(order_id: str, worker: str, exc: Exception) -> None:
    """A database outage while recording failure must not crash the process."""
    try:
        store.set_status(order_id, "FAILED", f"{worker}: {exc}", worker)
    except Exception:
        logs.setup(worker).exception("could not record FAILED for %s", order_id)
