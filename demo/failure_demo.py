"""Run one always-failing payment worker and verify retry plus dead-lettering."""

import os
import subprocess
import sys
import time
from urllib.parse import quote

import requests

from app import config
from scripts.reset import main as reset

BASE = "http://localhost:8000"
ORDER = {
    "customer": "Failure Demo",
    "restaurant": "Retry Kitchen",
    "items": ["Curry"],
    "total": 150.0,
}


def queue_count(queue: str) -> int:
    url = f"{config.RABBIT_HTTP}/api/queues/%2F/{quote(queue, safe='')}"
    response = requests.get(url, auth=(config.RABBIT_USER, config.RABBIT_PASS),
                            timeout=10)
    response.raise_for_status()
    return int(response.json()["messages"])


def main() -> int:
    if reset() != 0:
        return 1
    accepted = requests.post(f"{BASE}/orders", json=ORDER, timeout=10)
    accepted.raise_for_status()
    order_id = accepted.json()["order_id"]
    print(f"Queued {order_id}. Starting a payment worker with FAIL_RATE=1.0.")

    env = {**os.environ, "FAIL_RATE": "1.0"}
    worker = subprocess.Popen([sys.executable, "-m", "app.workers.payment_worker"],
                              env=env)
    try:
        deadline = time.time() + 30
        order = None
        while time.time() < deadline:
            order = requests.get(f"{BASE}/orders/{order_id}", timeout=5).json()
            if order["status"] == "FAILED":
                break
            time.sleep(0.25)
        if not order or order["status"] != "FAILED":
            print("Order did not reach FAILED:", order)
            return 1
        # RabbitMQ 4 updates management statistics asynchronously; the AMQP
        # dead-letter is immediate but its HTTP count can lag several seconds.
        deadline = time.time() + 20
        while queue_count(config.DLQ) != 1 and time.time() < deadline:
            time.sleep(0.2)
        stages = [event["stage"] for event in order["timeline"]]
        checks = {
            "one dead-letter": queue_count(config.DLQ) == 1,
            "failed status": order["status"] == "FAILED",
            "one restaurant ticket": stages.count("RESTAURANT_NOTIFIED") == 1,
            "one initial notification": stages.count("NOTIFIED") == 1,
        }
        for label, passed in checks.items():
            print(f"  {'PASS' if passed else 'FAIL'}  {label}")
        return 0 if all(checks.values()) else 1
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            worker.kill()


if __name__ == "__main__":
    raise SystemExit(main())
