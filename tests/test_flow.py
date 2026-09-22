import time

import pytest
import requests

from app import config


ORDER = {
    "customer": "Integration Test",
    "restaurant": "Test Kitchen",
    "items": ["Rice"],
    "total": 99.0,
}


def wait_for_terminal(base: str, order_id: str, timeout: float = 20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        order = requests.get(f"{base}/orders/{order_id}", timeout=5).json()
        if order["status"] in ("COMPLETED", "FAILED"):
            return order
        time.sleep(0.2)
    raise AssertionError(f"{order_id} did not reach a terminal state")


def test_health(live_stack):
    body = requests.get(f"{live_stack}/health", timeout=5).json()
    assert body["ok"] and body["broker"] and body["database"]


@pytest.mark.parametrize(
    "path,content_type,marker",
    [
        ("/", "text/html", "Order Flow Lab"),
        ("/static/styles.css", "text/css", "--orange"),
        ("/static/app.js", "javascript", "POLL_TIMEOUT_MS"),
    ],
)
def test_dashboard_assets(live_stack, path, content_type, marker):
    response = requests.get(f"{live_stack}{path}", timeout=5)
    assert response.status_code == 200
    assert content_type in response.headers["content-type"]
    assert marker in response.text


def test_invalid_order_is_rejected(live_stack):
    response = requests.post(f"{live_stack}/orders", json={**ORDER, "items": []},
                             timeout=5)
    assert response.status_code == 422


def test_unknown_order_is_404(live_stack):
    assert requests.get(f"{live_stack}/orders/NOT-REAL", timeout=5).status_code == 404


def test_async_order_completes_with_expected_timeline(live_stack):
    response = requests.post(f"{live_stack}/orders", json=ORDER, timeout=5)
    assert response.status_code == 202
    accepted = response.json()
    assert accepted["status"] == "PENDING"
    assert accepted["track"] == f"/orders/{accepted['order_id']}"
    order = wait_for_terminal(live_stack, accepted["order_id"])
    assert order["status"] == "COMPLETED"
    stages = [event["stage"] for event in order["timeline"]]
    assert stages.count("NOTIFIED") == 2
    assert {"PENDING", "PAYMENT_PROCESSING", "PAID", "RESTAURANT_NOTIFIED",
            "INVENTORY_RESERVED", "COMPLETED"}.issubset(stages)


def test_sync_order_is_slow_and_complete(live_stack):
    response = requests.post(f"{live_stack}/orders/sync", json=ORDER, timeout=10)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    expected_ms = (config.T_PAYMENT + config.T_RESTAURANT +
                   config.T_INVENTORY + config.T_NOTIFICATION) * 1000
    assert body["api_time_ms"] >= expected_ms * 0.8
