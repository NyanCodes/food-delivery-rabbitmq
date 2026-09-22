"""Charge an order and publish a durable payment-success result."""

import random
import time

from app import config, store
from app.workers.base import run_worker

WORKER = "payment"


def handle(payload: dict, ctx) -> None:
    order_id = payload["order_id"]
    store.ensure_processing(order_id, WORKER)
    if store.workflow_step_done(order_id, "payment"):
        ctx.emit(config.RK_PAYMENT_SUCCEEDED, payload)
        return

    time.sleep(config.T_PAYMENT)
    if (config.PAYMENT_FAIL_RATE
            and random.random() < config.PAYMENT_FAIL_RATE):
        raise RuntimeError("payment gateway timeout")
    store.record_step_success(
        order_id,
        "payment",
        "PAYMENT_SUCCEEDED",
        f"charged {payload['total']:.2f} THB",
        WORKER,
    )
    ctx.log.info("   charged %.2f THB", payload["total"])
    ctx.emit(config.RK_PAYMENT_SUCCEEDED, payload)


if __name__ == "__main__":
    run_worker(config.Q_PAYMENT, handle, name=WORKER, critical=True)
