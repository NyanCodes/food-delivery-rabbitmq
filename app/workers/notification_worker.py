"""Send truthful receipt, confirmation, and failure notifications."""

import time

from app import config, store
from app.workers.base import run_worker

WORKER = "notification"
MESSAGES = {
    config.RK_ORDER_CREATED: (
        "Thanks {customer}! We received your order and are confirming payment "
        "and availability."
    ),
    config.RK_ORDER_CONFIRMED: (
        "Order confirmed by {restaurant}. Payment and inventory are secured."
    ),
    config.RK_ORDER_FAILED: (
        "Sorry {customer}, your order could not be confirmed. Any completed "
        "payment or inventory hold has been reversed."
    ),
}


def handle(payload: dict, ctx) -> None:
    order_id = payload["order_id"]
    time.sleep(config.T_NOTIFICATION)
    message = MESSAGES[ctx.routing_key].format(**payload)
    if ctx.routing_key == config.RK_ORDER_CREATED:
        recorded = store.add_event_once(
            order_id, "NOTIFIED", message, WORKER, "notification.received"
        )
    elif ctx.routing_key == config.RK_ORDER_CONFIRMED:
        recorded = store.complete_order(order_id, message, WORKER)
    else:
        recorded = store.add_event_once(
            order_id, "FAILURE_NOTIFIED", message, WORKER,
            "notification.failed_order",
        )
    if recorded:
        ctx.log.info("   push: %s", message)


if __name__ == "__main__":
    run_worker(config.Q_NOTIFICATION, handle, name=WORKER, critical=False)
