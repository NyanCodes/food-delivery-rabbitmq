"""Send a restaurant ticket only after the order is ready."""

import random
import time

from app import config, store
from app.workers.base import run_worker

WORKER = "restaurant"


def handle(payload: dict, ctx) -> None:
    order_id = payload["order_id"]
    if store.workflow_is_failed(order_id):
        return
    if store.workflow_step_done(order_id, "restaurant"):
        ctx.emit(config.RK_ORDER_CONFIRMED, payload)
        return

    time.sleep(config.T_RESTAURANT)
    if (config.RESTAURANT_FAIL_RATE
            and random.random() < config.RESTAURANT_FAIL_RATE):
        raise RuntimeError("restaurant ticket delivery failed")
    if not store.record_restaurant_confirmation(
        order_id,
        f"ticket sent to {payload['restaurant']}",
        WORKER,
    ):
        return
    ctx.log.info("   ticket printed at %s", payload["restaurant"])
    ctx.emit(config.RK_ORDER_CONFIRMED, payload)


if __name__ == "__main__":
    run_worker(config.Q_RESTAURANT, handle, name=WORKER, critical=True)
