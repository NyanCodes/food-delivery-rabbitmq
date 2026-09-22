"""Charge an order and publish the order.paid event."""

import random
import time

from app import config, store
from app.workers.base import run_worker

WORKER = "payment"


def handle(payload: dict, ctx) -> None:
    order_id = payload["order_id"]
    store.set_status(order_id, "PAYMENT_PROCESSING", worker=WORKER)
    time.sleep(config.T_PAYMENT)
    if config.FAIL_RATE and random.random() < config.FAIL_RATE:
        raise RuntimeError("payment gateway timeout")
    store.set_status(order_id, "PAID",
                     f"charged {payload['total']:.2f} THB", WORKER)
    ctx.log.info("   charged %.2f THB", payload["total"])
    ctx.emit(config.RK_ORDER_PAID, payload)


if __name__ == "__main__":
    run_worker(config.Q_PAYMENT, handle, name=WORKER)
