"""Send the restaurant ticket and reserve its inventory."""

import time

from app import config, store
from app.workers.base import run_worker

WORKER = "restaurant"


def handle(payload: dict, ctx) -> None:
    order_id = payload["order_id"]
    time.sleep(config.T_RESTAURANT)
    store.add_event(order_id, "RESTAURANT_NOTIFIED",
                    f"ticket sent to {payload['restaurant']}", WORKER)
    ctx.log.info("   ticket printed at %s", payload["restaurant"])
    time.sleep(config.T_INVENTORY)
    store.add_event(order_id, "INVENTORY_RESERVED",
                    f"{len(payload['items'])} item(s) reserved", WORKER)
    ctx.log.info("   reserved %s item(s)", len(payload["items"]))


if __name__ == "__main__":
    run_worker(config.Q_RESTAURANT, handle, name=WORKER)
