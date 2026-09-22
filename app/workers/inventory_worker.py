"""Reserve inventory independently and publish the successful result."""

import random
import time

from app import config, store
from app.workers.base import run_worker

WORKER = "inventory"


def handle(payload: dict, ctx) -> None:
    order_id = payload["order_id"]
    store.ensure_processing(order_id, WORKER)
    if store.workflow_step_done(order_id, "inventory"):
        ctx.emit(config.RK_INVENTORY_RESERVED, payload)
        return

    time.sleep(config.T_INVENTORY)
    if (config.INVENTORY_FAIL_RATE
            and random.random() < config.INVENTORY_FAIL_RATE):
        raise RuntimeError("inventory reservation rejected")
    store.record_step_success(
        order_id,
        "inventory",
        "INVENTORY_RESERVED",
        f"{len(payload['items'])} item(s) reserved",
        WORKER,
    )
    ctx.log.info("   reserved %s item(s)", len(payload["items"]))
    ctx.emit(config.RK_INVENTORY_RESERVED, payload)


if __name__ == "__main__":
    run_worker(config.Q_INVENTORY, handle, name=WORKER, critical=True)
