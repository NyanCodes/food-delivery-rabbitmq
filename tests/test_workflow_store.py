import uuid
from types import SimpleNamespace

import pytest

from app import config, store
from app.workers import coordinator_worker, notification_worker


class Context:
    def __init__(self, routing_key: str):
        self.routing_key = routing_key
        self.emitted = []
        self.log = SimpleNamespace(info=lambda *_args: None)

    def emit(self, routing_key, payload):
        self.emitted.append((routing_key, payload))


def make_order(prefix: str) -> str:
    order_id = f"{prefix}-{uuid.uuid4().hex[:8].upper()}"
    store.create_order(order_id, "Workflow Test", "Test Kitchen", ["Rice"], 99)
    return order_id


def stages(order_id: str) -> list[str]:
    return [event["stage"] for event in store.get_order(order_id)["timeline"]]


def test_payment_only_never_becomes_ready_and_is_refunded_on_failure(live_stack):
    order_id = make_order("PAY")
    store.record_step_success(
        order_id, "payment", "PAYMENT_SUCCEEDED", "charged", "test"
    )
    assert store.prepare_order_ready(order_id) is False
    assert store.fail_workflow(order_id, "inventory", "out of stock") is True
    store.mark_failure_published(order_id)
    assert store.fail_workflow(order_id, "inventory", "duplicate") is False
    timeline = stages(order_id)
    assert timeline.count("FAILED") == 1
    assert timeline.count("PAYMENT_REFUNDED") == 1
    assert "RESTAURANT_NOTIFIED" not in timeline


def test_inventory_only_never_becomes_ready_and_is_released_on_failure(live_stack):
    order_id = make_order("INV")
    store.record_step_success(
        order_id, "inventory", "INVENTORY_RESERVED", "reserved", "test"
    )
    assert store.prepare_order_ready(order_id) is False
    assert store.fail_workflow(order_id, "payment", "declined") is True
    timeline = stages(order_id)
    assert timeline.count("FAILED") == 1
    assert timeline.count("INVENTORY_RELEASED") == 1
    assert "RESTAURANT_NOTIFIED" not in timeline


def test_join_and_downstream_side_effects_are_idempotent(live_stack):
    order_id = make_order("JOIN")
    for step, stage in (("inventory", "INVENTORY_RESERVED"),
                        ("payment", "PAYMENT_SUCCEEDED")):
        store.record_step_success(order_id, step, stage, "ok", "test")
        store.record_step_success(order_id, step, stage, "duplicate", "test")

    assert store.prepare_order_ready(order_id) is True
    store.mark_ready_published(order_id)
    assert store.prepare_order_ready(order_id) is False
    assert store.record_restaurant_confirmation(order_id, "sent", "test") is True
    assert store.record_restaurant_confirmation(order_id, "duplicate", "test") is False
    assert store.complete_order(order_id, "confirmed", "test") is True
    assert store.complete_order(order_id, "duplicate", "test") is False

    timeline = stages(order_id)
    assert timeline.count("PAYMENT_SUCCEEDED") == 1
    assert timeline.count("INVENTORY_RESERVED") == 1
    assert timeline.count("READY") == 1
    assert timeline.count("RESTAURANT_NOTIFIED") == 1
    assert timeline.count("COMPLETED") == 1


@pytest.mark.parametrize(
    "successful_steps,failed_step,compensations",
    [
        (("inventory",), "payment", {"INVENTORY_RELEASED"}),
        (("payment",), "inventory", {"PAYMENT_REFUNDED"}),
        (("payment", "inventory"), "restaurant",
         {"PAYMENT_REFUNDED", "INVENTORY_RELEASED"}),
    ],
)
def test_critical_failure_compensates_and_sends_no_success(
        live_stack, monkeypatch, successful_steps, failed_step, compensations):
    order_id = make_order("FAIL")
    payload = {
        "order_id": order_id,
        "customer": "Workflow Test",
        "restaurant": "Test Kitchen",
        "items": ["Rice"],
        "total": 99.0,
    }
    for step in successful_steps:
        stage = "PAYMENT_SUCCEEDED" if step == "payment" else "INVENTORY_RESERVED"
        store.record_step_success(order_id, step, stage, "ok", "test")

    failure = {**payload, "failed_step": failed_step,
               "failure_reason": "simulated failure"}
    coordinator_ctx = Context(config.RK_WORKFLOW_FAILED)
    coordinator_worker.handle(failure, coordinator_ctx)
    assert coordinator_ctx.emitted == [(config.RK_ORDER_FAILED, failure)]

    monkeypatch.setattr(notification_worker.time, "sleep", lambda _seconds: None)
    notification_worker.handle(failure, Context(config.RK_ORDER_FAILED))
    timeline = stages(order_id)
    assert store.get_order(order_id)["status"] == "FAILED"
    assert compensations.issubset(timeline)
    assert timeline.count("FAILURE_NOTIFIED") == 1
    assert "RESTAURANT_NOTIFIED" not in timeline
    assert "COMPLETED" not in timeline
