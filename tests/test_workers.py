from types import SimpleNamespace

from app import config
from app.workers import (coordinator_worker, inventory_worker,
                         notification_worker, payment_worker,
                         restaurant_worker)


class Context:
    def __init__(self, routing_key=config.RK_ORDER_CREATED):
        self.routing_key = routing_key
        self.emitted = []
        self.log = SimpleNamespace(info=lambda *_args: None)

    def emit(self, routing_key, payload):
        self.emitted.append((routing_key, payload))


PAYLOAD = {
    "order_id": "ORD-123",
    "customer": "Aung",
    "restaurant": "Shan Noodle House",
    "items": ["Noodles", "Tea"],
    "total": 180.0,
}


def test_payment_records_success_and_emits_result(monkeypatch):
    recorded = []
    monkeypatch.setattr(payment_worker.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(payment_worker.config, "PAYMENT_FAIL_RATE", 0.0)
    monkeypatch.setattr(payment_worker.store, "ensure_processing", lambda *_args: True)
    monkeypatch.setattr(payment_worker.store, "workflow_step_done", lambda *_args: False)
    monkeypatch.setattr(payment_worker.store, "record_step_success",
                        lambda *args: recorded.append(args))
    ctx = Context()
    payment_worker.handle(PAYLOAD, ctx)
    assert recorded[0][1:3] == ("payment", "PAYMENT_SUCCEEDED")
    assert ctx.emitted == [(config.RK_PAYMENT_SUCCEEDED, PAYLOAD)]


def test_inventory_records_success_and_emits_result(monkeypatch):
    recorded = []
    monkeypatch.setattr(inventory_worker.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(inventory_worker.config, "INVENTORY_FAIL_RATE", 0.0)
    monkeypatch.setattr(inventory_worker.store, "ensure_processing", lambda *_args: True)
    monkeypatch.setattr(inventory_worker.store, "workflow_step_done", lambda *_args: False)
    monkeypatch.setattr(inventory_worker.store, "record_step_success",
                        lambda *args: recorded.append(args))
    ctx = Context()
    inventory_worker.handle(PAYLOAD, ctx)
    assert recorded[0][1:3] == ("inventory", "INVENTORY_RESERVED")
    assert ctx.emitted == [(config.RK_INVENTORY_RESERVED, PAYLOAD)]


def test_coordinator_does_not_release_one_prerequisite(monkeypatch):
    monkeypatch.setattr(coordinator_worker.store, "prepare_order_ready",
                        lambda _order_id: False)
    ctx = Context(config.RK_PAYMENT_SUCCEEDED)
    coordinator_worker.handle(PAYLOAD, ctx)
    assert ctx.emitted == []


def test_coordinator_releases_ready_once_join_is_complete(monkeypatch):
    marked = []
    monkeypatch.setattr(coordinator_worker.store, "prepare_order_ready",
                        lambda _order_id: True)
    monkeypatch.setattr(coordinator_worker.store, "mark_ready_published",
                        lambda order_id: marked.append(order_id))
    ctx = Context(config.RK_INVENTORY_RESERVED)
    coordinator_worker.handle(PAYLOAD, ctx)
    assert ctx.emitted == [(config.RK_ORDER_READY, PAYLOAD)]
    assert marked == [PAYLOAD["order_id"]]


def test_restaurant_only_confirms_ready_order(monkeypatch):
    monkeypatch.setattr(restaurant_worker.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(restaurant_worker.config, "RESTAURANT_FAIL_RATE", 0.0)
    monkeypatch.setattr(restaurant_worker.store, "workflow_is_failed",
                        lambda _order_id: False)
    monkeypatch.setattr(restaurant_worker.store, "workflow_step_done",
                        lambda *_args: False)
    monkeypatch.setattr(restaurant_worker.store, "record_restaurant_confirmation",
                        lambda *_args: True)
    ctx = Context(config.RK_ORDER_READY)
    restaurant_worker.handle(PAYLOAD, ctx)
    assert ctx.emitted == [(config.RK_ORDER_CONFIRMED, PAYLOAD)]


def test_created_notification_is_truthful_and_does_not_complete(monkeypatch):
    messages = []
    monkeypatch.setattr(notification_worker.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(notification_worker.store, "add_event_once",
                        lambda _order_id, _stage, detail, *_args:
                        messages.append(detail) or True)
    monkeypatch.setattr(notification_worker.store, "complete_order",
                        lambda *_args: (_ for _ in ()).throw(
                            AssertionError("must not complete")))
    notification_worker.handle(PAYLOAD, Context(config.RK_ORDER_CREATED))
    assert "confirming payment and availability" in messages[0]
    assert "has your order" not in messages[0]


def test_confirmed_notification_completes(monkeypatch):
    completed = []
    monkeypatch.setattr(notification_worker.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(notification_worker.store, "complete_order",
                        lambda *args: completed.append(args) or True)
    notification_worker.handle(PAYLOAD, Context(config.RK_ORDER_CONFIRMED))
    assert completed[0][0] == PAYLOAD["order_id"]


def test_failed_notification_never_completes(monkeypatch):
    stages = []
    monkeypatch.setattr(notification_worker.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(notification_worker.store, "add_event_once",
                        lambda _order_id, stage, *_args:
                        stages.append(stage) or True)
    monkeypatch.setattr(notification_worker.store, "complete_order",
                        lambda *_args: (_ for _ in ()).throw(
                            AssertionError("must not complete")))
    notification_worker.handle(PAYLOAD, Context(config.RK_ORDER_FAILED))
    assert stages == ["FAILURE_NOTIFIED"]


def test_coordinator_failure_publishes_customer_failure(monkeypatch):
    marked = []
    monkeypatch.setattr(coordinator_worker.store, "fail_workflow",
                        lambda *_args: True)
    monkeypatch.setattr(coordinator_worker.store, "mark_failure_published",
                        lambda order_id: marked.append(order_id))
    failed = {**PAYLOAD, "failed_step": "inventory",
              "failure_reason": "out of stock"}
    ctx = Context(config.RK_WORKFLOW_FAILED)
    coordinator_worker.handle(failed, ctx)
    assert ctx.emitted == [(config.RK_ORDER_FAILED, failed)]
    assert marked == [PAYLOAD["order_id"]]
