from types import SimpleNamespace

from app import config
from app.workers import notification_worker, payment_worker, restaurant_worker


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


def test_payment_sets_status_and_emits_paid(monkeypatch):
    changes = []
    monkeypatch.setattr(payment_worker.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(payment_worker.config, "FAIL_RATE", 0.0)
    monkeypatch.setattr(payment_worker.store, "set_status",
                        lambda *args, **kwargs: changes.append((args, kwargs)))
    ctx = Context()
    payment_worker.handle(PAYLOAD, ctx)
    assert changes[0][0][1] == "PAYMENT_PROCESSING"
    assert changes[-1][0][1] == "PAID"
    assert ctx.emitted == [(config.RK_ORDER_PAID, PAYLOAD)]


def test_restaurant_records_both_events(monkeypatch):
    events = []
    monkeypatch.setattr(restaurant_worker.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(restaurant_worker.store, "add_event",
                        lambda *args: events.append(args))
    restaurant_worker.handle(PAYLOAD, Context())
    assert [event[1] for event in events] == ["RESTAURANT_NOTIFIED",
                                             "INVENTORY_RESERVED"]


def test_created_notification_does_not_complete(monkeypatch):
    events, statuses = [], []
    monkeypatch.setattr(notification_worker.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(notification_worker.store, "add_event",
                        lambda *args: events.append(args))
    monkeypatch.setattr(notification_worker.store, "set_status",
                        lambda *args: statuses.append(args))
    notification_worker.handle(PAYLOAD, Context(config.RK_ORDER_CREATED))
    assert len(events) == 1
    assert statuses == []


def test_paid_notification_completes(monkeypatch):
    statuses = []
    monkeypatch.setattr(notification_worker.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(notification_worker.store, "add_event", lambda *_args: None)
    monkeypatch.setattr(notification_worker.store, "set_status",
                        lambda *args: statuses.append(args))
    notification_worker.handle(PAYLOAD, Context(config.RK_ORDER_PAID))
    assert statuses[0][1] == "COMPLETED"
