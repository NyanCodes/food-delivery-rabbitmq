"""HTTP producer and presentation console for the food-order demo."""

import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import broker, config, db, logs, store
from app.models import Health, OrderAccepted, OrderCompleted, OrderIn

log = logs.setup("api")
publisher = broker.Publisher()
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Refuse to start if either required dependency is unavailable."""
    db.wait_for_db()
    publisher.start()
    log.info("api ready - broker and database are reachable")
    yield
    publisher.close()
    db.close()


app = FastAPI(
    title="Food Delivery Order API",
    description="Synchronous and RabbitMQ-backed order processing demo",
    version="2.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health", response_model=Health)
def health():
    broker_ok = publisher.healthy()
    database_ok = db.healthy()
    return Health(ok=broker_ok and database_ok, broker=broker_ok,
                  database=database_ok, service=config.SERVICE_NAME)


@app.get("/stats")
def stats():
    return store.counts_by_status()


@app.post("/orders", status_code=202, response_model=OrderAccepted)
def create_order_async(order: OrderIn):
    """Persist an order, publish one event, and release the caller."""
    started = time.perf_counter()
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    store.create_order(order_id, order.customer, order.restaurant,
                       order.items, order.total, status="PENDING")
    try:
        publisher.publish(config.RK_ORDER_CREATED,
                          {"order_id": order_id, **order.model_dump()})
    except Exception as exc:
        store.set_status(order_id, "FAILED", f"publish: {exc}", "api")
        log.exception("could not publish %s", order_id)
        raise HTTPException(status_code=503,
                            detail="order broker unavailable") from exc

    return OrderAccepted(
        order_id=order_id,
        status="PENDING",
        api_time_ms=round((time.perf_counter() - started) * 1000, 1),
        track=f"/orders/{order_id}",
    )


@app.post("/orders/sync", response_model=OrderCompleted)
def create_order_sync(order: OrderIn):
    """Perform the same simulated work serially inside the HTTP request."""
    started = time.perf_counter()
    order_id = f"SYN-{uuid.uuid4().hex[:8].upper()}"
    store.create_order(order_id, order.customer, order.restaurant,
                       order.items, order.total, status="PENDING")
    time.sleep(config.T_PAYMENT)
    store.set_status(order_id, "PAID", "charged inline", "sync")
    time.sleep(config.T_RESTAURANT)
    store.add_event(order_id, "RESTAURANT_NOTIFIED", "inline", "sync")
    time.sleep(config.T_INVENTORY)
    store.add_event(order_id, "INVENTORY_RESERVED", "inline", "sync")
    time.sleep(config.T_NOTIFICATION)
    store.set_status(order_id, "COMPLETED", "notified inline", "sync")
    return OrderCompleted(
        order_id=order_id,
        status="COMPLETED",
        api_time_ms=round((time.perf_counter() - started) * 1000, 1),
    )


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    order = store.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="unknown order")
    return order


@app.get("/", response_class=FileResponse)
def demo_page():
    return FileResponse(STATIC_DIR / "index.html")
