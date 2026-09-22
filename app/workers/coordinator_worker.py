"""Join parallel outcomes and release only safe downstream work."""

from app import config, store
from app.workers.base import run_worker

WORKER = "coordinator"


def handle(payload: dict, ctx) -> None:
    order_id = payload["order_id"]

    if ctx.routing_key == config.RK_WORKFLOW_FAILED:
        should_publish = store.fail_workflow(
            order_id,
            payload["failed_step"],
            payload.get("failure_reason", "step failed after retries"),
        )
        if should_publish:
            ctx.emit(config.RK_ORDER_FAILED, payload)
            store.mark_failure_published(order_id)
        return

    if ctx.routing_key not in {
        config.RK_PAYMENT_SUCCEEDED,
        config.RK_INVENTORY_RESERVED,
    }:
        raise ValueError(f"unsupported coordinator event: {ctx.routing_key}")

    if store.prepare_order_ready(order_id):
        ctx.emit(config.RK_ORDER_READY, payload)
        store.mark_ready_published(order_id)


if __name__ == "__main__":
    run_worker(config.Q_COORDINATOR, handle, name=WORKER, critical=True)
