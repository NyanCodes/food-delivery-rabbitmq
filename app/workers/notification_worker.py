"""Send order-created and payment-confirmed customer notifications."""

import time

from app import config, store
from app.workers.base import run_worker

WORKER = "notification"
MESSAGES = {
    config.RK_ORDER_CREATED: "Thanks {customer}! {restaurant} has your order.",
    config.RK_ORDER_PAID: "Payment of {total:.2f} THB confirmed. Food is on the way.",
}


def handle(payload: dict, ctx) -> None:
    order_id = payload["order_id"]
    time.sleep(config.T_NOTIFICATION)
    message = MESSAGES[ctx.routing_key].format(**payload)
    store.add_event(order_id, "NOTIFIED", message, WORKER)
    ctx.log.info("   push: %s", message)
    if ctx.routing_key == config.RK_ORDER_PAID:
        store.set_status(order_id, "COMPLETED", "customer notified", WORKER)


if __name__ == "__main__":
    run_worker(config.Q_NOTIFICATION, handle, name=WORKER)
