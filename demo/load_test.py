"""Compare API latency for synchronous and RabbitMQ-backed orders."""

import argparse
import concurrent.futures
import statistics
import time

import requests

BASE = "http://localhost:8000"
ORDER = {
    "customer": "Load Test",
    "restaurant": "Bangkok Kitchen",
    "items": ["Pad kra pao", "Iced tea"],
    "total": 220.0,
}


def percentile(values: list[float], proportion: float) -> float:
    ordered = sorted(values)
    position = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * proportion)))
    return ordered[position]


def place(path: str) -> tuple[str, float]:
    started = time.perf_counter()
    response = requests.post(f"{BASE}{path}", json=ORDER, timeout=30)
    response.raise_for_status()
    body = response.json()
    return body["order_id"], (time.perf_counter() - started) * 1000


def run(path: str, count: int, concurrency: int) -> tuple[list[str], list[float], float]:
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(lambda _index: place(path), range(count)))
    return [item[0] for item in results], [item[1] for item in results], time.perf_counter() - started


def wait_for_orders(order_ids: list[str], timeout: float = 120) -> int:
    remaining = set(order_ids)
    deadline = time.time() + timeout
    while remaining and time.time() < deadline:
        for order_id in list(remaining):
            body = requests.get(f"{BASE}/orders/{order_id}", timeout=10).json()
            if body["status"] in ("COMPLETED", "FAILED"):
                remaining.remove(order_id)
        if remaining:
            time.sleep(0.25)
    return len(order_ids) - len(remaining)


def print_row(name: str, latencies: list[float], wall: float, completed: int) -> None:
    print(f"{name:12} mean={statistics.mean(latencies):8.1f} ms  "
          f"p50={percentile(latencies, .50):8.1f} ms  "
          f"p95={percentile(latencies, .95):8.1f} ms  "
          f"wall={wall:6.2f} s  completed={completed}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("count", type=int, nargs="?", default=30)
    parser.add_argument("concurrency", type=int, nargs="?", default=6)
    args = parser.parse_args()
    requests.get(f"{BASE}/health", timeout=10).raise_for_status()

    sync_ids, sync_latency, sync_wall = run("/orders/sync", args.count, args.concurrency)
    async_ids, async_latency, async_wall = run("/orders", args.count, args.concurrency)
    async_completed = wait_for_orders(async_ids)

    print("\nAPI response comparison")
    print_row("synchronous", sync_latency, sync_wall, len(sync_ids))
    print_row("RabbitMQ", async_latency, async_wall, async_completed)
    return 0 if async_completed == len(async_ids) else 1


if __name__ == "__main__":
    raise SystemExit(main())
