"""Central configuration.

Every setting is read from an environment variable with a sensible local
default, so the identical code runs three ways with no edits:

  1. everything on your laptop        (defaults point at localhost)
  2. app on your laptop, infra in Docker
  3. everything in Docker             (compose sets the service hostnames)
"""
import os


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _i(name: str, default: int) -> int:
    return int(os.getenv(name, default))


# --------------------------------------------------------------------------
# Connections
# --------------------------------------------------------------------------
AMQP_URL = os.getenv("AMQP_URL", "amqp://guest:guest@localhost:5672/%2F")
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/orders"
)

# The management UI's HTTP API, used by scripts/reset.py to purge queues.
RABBIT_HTTP = os.getenv("RABBIT_HTTP", "http://localhost:15672")
RABBIT_USER = os.getenv("RABBIT_USER", "guest")
RABBIT_PASS = os.getenv("RABBIT_PASS", "guest")

# --------------------------------------------------------------------------
# Topology — names are configuration, not magic strings scattered in code
# --------------------------------------------------------------------------
EXCHANGE = os.getenv("EXCHANGE", "orders")
EXCHANGE_TYPE = "topic"

DLX = "orders.dlx"
DLQ = "orders.dlq"

RK_ORDER_CREATED = "order.created"
RK_PAYMENT_SUCCEEDED = "payment.succeeded"
RK_INVENTORY_RESERVED = "inventory.reserved"
RK_WORKFLOW_FAILED = "workflow.failed"
RK_ORDER_READY = "order.ready"
RK_ORDER_CONFIRMED = "order.confirmed"
RK_ORDER_FAILED = "order.failed"

Q_PAYMENT = "payment.process"
Q_INVENTORY = "inventory.reserve"
Q_COORDINATOR = "order.coordinate"
Q_RESTAURANT = "restaurant.notify"
Q_NOTIFICATION = "notification.send"

# queue name -> the routing keys it subscribes to
QUEUES: dict[str, list[str]] = {
    Q_PAYMENT: [RK_ORDER_CREATED],
    Q_INVENTORY: [RK_ORDER_CREATED],
    Q_COORDINATOR: [
        RK_PAYMENT_SUCCEEDED,
        RK_INVENTORY_RESERVED,
        RK_WORKFLOW_FAILED,
    ],
    Q_RESTAURANT: [RK_ORDER_READY],
    Q_NOTIFICATION: [
        RK_ORDER_CREATED,
        RK_ORDER_CONFIRMED,
        RK_ORDER_FAILED,
    ],
}

# --------------------------------------------------------------------------
# Worker behaviour
# --------------------------------------------------------------------------
PREFETCH = _i("PREFETCH", 1)          # un-acked messages allowed per worker
MAX_RETRIES = _i("MAX_RETRIES", 3)    # attempts before the dead-letter queue
HEARTBEAT = _i("HEARTBEAT", 60)       # AMQP heartbeat, seconds

# --------------------------------------------------------------------------
# Simulated third parties (seconds). These sleeps ARE the pain point.
# --------------------------------------------------------------------------
T_PAYMENT = _f("T_PAYMENT", 0.8)
T_RESTAURANT = _f("T_RESTAURANT", 0.5)
T_INVENTORY = _f("T_INVENTORY", 0.3)
T_NOTIFICATION = _f("T_NOTIFICATION", 0.4)

# Per-step failure probabilities (0.0-1.0). FAIL_RATE remains a compatibility
# fallback for the original payment-only failure demo.
FAIL_RATE = _f("FAIL_RATE", 0.0)
PAYMENT_FAIL_RATE = _f("PAYMENT_FAIL_RATE", FAIL_RATE)
INVENTORY_FAIL_RATE = _f("INVENTORY_FAIL_RATE", 0.0)
RESTAURANT_FAIL_RATE = _f("RESTAURANT_FAIL_RATE", 0.0)

# --------------------------------------------------------------------------
# Startup patience — containers start in parallel, so wait rather than crash
# --------------------------------------------------------------------------
CONNECT_RETRIES = _i("CONNECT_RETRIES", 30)
CONNECT_DELAY = _f("CONNECT_DELAY", 2.0)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
SERVICE_NAME = os.getenv("SERVICE_NAME", "app")
