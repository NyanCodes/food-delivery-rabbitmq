"""Guided proof that orders wait safely while the payment worker is down."""

import time

import requests

BASE = "http://localhost:8000"
ORDER = {
    "customer": "Chaos Demo",
    "restaurant": "Mandalay Grill",
    "items": ["Tea leaf salad"],
    "total": 120.0,
}


def place(count: int = 5) -> list[str]:
    order_ids = []
    for _ in range(count):
        response = requests.post(f"{BASE}/orders", json=ORDER, timeout=10)
        response.raise_for_status()
        body = response.json()
        order_ids.append(body["order_id"])
        print(f"  accepted {body['order_id']} in {body['api_time_ms']} ms")
    return order_ids


def statuses(order_ids: list[str]) -> list[str]:
    return [requests.get(f"{BASE}/orders/{order_id}", timeout=10).json()["status"]
            for order_id in order_ids]


def main() -> int:
    health = requests.get(f"{BASE}/health", timeout=10).json()
    if not health.get("ok"):
        print("Stack is not healthy:", health)
        return 1

    input("\n1. Run 'docker compose stop payment-worker', then press Enter.\n> ")
    print("\n2. Placing five orders while payment is unavailable:")
    order_ids = place()
    print("   Current statuses:", "  ".join(statuses(order_ids)))
    print("   The API accepted every order; payment messages are waiting in RabbitMQ.")

    input("\n3. Run 'docker compose start payment-worker', then press Enter.\n> ")
    deadline = time.time() + 120
    latest = statuses(order_ids)
    while time.time() < deadline:
        latest = statuses(order_ids)
        print("  ", "  ".join(latest))
        if all(status == "COMPLETED" for status in latest):
            print("\nZero orders lost. The durable queue drained after recovery.")
            return 0
        time.sleep(2)
    print("Timed out. Final statuses:", latest)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
