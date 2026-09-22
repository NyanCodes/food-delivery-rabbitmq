"""Every SQL statement in the project lives here.

Keeping queries out of the API and the workers means the handlers read like
business steps ("mark it paid") rather than plumbing, and there is exactly one
place to look when the schema changes.
"""
import json

from app import db


def create_order(order_id: str, customer: str, restaurant: str,
                 items: list[str], total: float, status: str = "PENDING") -> None:
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO orders (id, customer, restaurant, items, total, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (order_id, customer, restaurant, json.dumps(items), total, status),
        )
        cur.execute(
            """
            INSERT INTO order_events (order_id, stage, detail, worker, event_key)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (order_id, status, "order accepted", "api", "order.accepted"),
        )
        cur.execute(
            "INSERT INTO order_workflow (order_id) VALUES (%s)",
            (order_id,),
        )


def set_status(order_id: str, status: str, detail: str | None = None,
               worker: str | None = None) -> None:
    """Move the ticket to a new state and record the transition."""
    with db.cursor() as cur:
        cur.execute(
            "UPDATE orders SET status = %s, updated_at = now() WHERE id = %s",
            (status, order_id),
        )
        cur.execute(
            """
            INSERT INTO order_events (order_id, stage, detail, worker)
            VALUES (%s, %s, %s, %s)
            """,
            (order_id, status, detail, worker),
        )


def add_event(order_id: str, stage: str, detail: str | None = None,
              worker: str | None = None) -> None:
    """Record a step that is not itself a status change."""
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO order_events (order_id, stage, detail, worker)
            VALUES (%s, %s, %s, %s)
            """,
            (order_id, stage, detail, worker),
        )


def add_event_once(order_id: str, stage: str, detail: str | None,
                   worker: str | None, event_key: str) -> bool:
    """Record one logical event despite redelivery or duplicate messages."""
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO order_events
                (order_id, stage, detail, worker, event_key)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (order_id, stage, detail, worker, event_key),
        )
        return cur.rowcount == 1


def ensure_processing(order_id: str, worker: str) -> bool:
    """Move PENDING to PROCESSING once; parallel workers cannot race it."""
    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE orders
               SET status = 'PROCESSING', updated_at = now()
             WHERE id = %s AND status = 'PENDING'
            RETURNING id
            """,
            (order_id,),
        )
        changed = cur.fetchone() is not None
        if changed:
            cur.execute(
                """
                INSERT INTO order_events
                    (order_id, stage, detail, worker, event_key)
                VALUES (%s, 'PROCESSING', 'parallel checks started', %s,
                        'workflow.processing')
                ON CONFLICT DO NOTHING
                """,
                (order_id, worker),
            )
        return changed


_STEP_COLUMNS = {
    "payment": "payment_succeeded",
    "inventory": "inventory_reserved",
    "restaurant": "restaurant_notified",
}


def workflow_step_done(order_id: str, step: str) -> bool:
    column = _STEP_COLUMNS[step]
    with db.cursor(commit=False) as cur:
        cur.execute(
            f"SELECT {column} AS done FROM order_workflow WHERE order_id = %s",
            (order_id,),
        )
        row = cur.fetchone()
        return bool(row and row["done"])


def workflow_is_failed(order_id: str) -> bool:
    with db.cursor(commit=False) as cur:
        cur.execute(
            "SELECT failed_step IS NOT NULL AS failed "
            "FROM order_workflow WHERE order_id = %s",
            (order_id,),
        )
        row = cur.fetchone()
        return bool(row and row["failed"])


def record_step_success(order_id: str, step: str, stage: str, detail: str,
                        worker: str) -> bool:
    """Persist a successful parallel step before its RabbitMQ result."""
    column = _STEP_COLUMNS[step]
    with db.cursor() as cur:
        cur.execute(
            f"""
            UPDATE order_workflow
               SET {column} = TRUE
             WHERE order_id = %s AND {column} = FALSE
            RETURNING failed_step
            """,
            (order_id,),
        )
        row = cur.fetchone()
        if row is None:
            return False
        cur.execute(
            """
            INSERT INTO order_events
                (order_id, stage, detail, worker, event_key)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (order_id, stage, detail, worker, f"step.{step}.succeeded"),
        )
        if row["failed_step"] is not None:
            _record_compensations(cur, order_id)
        return True


def prepare_order_ready(order_id: str) -> bool:
    """Persist READY and report whether order.ready still needs publishing."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT payment_succeeded, inventory_reserved, ready_published,
                   failed_step
              FROM order_workflow
             WHERE order_id = %s
             FOR UPDATE
            """,
            (order_id,),
        )
        row = cur.fetchone()
        if (row is None or row["failed_step"] is not None
                or not row["payment_succeeded"]
                or not row["inventory_reserved"]):
            return False
        cur.execute(
            """
            UPDATE orders
               SET status = 'READY', updated_at = now()
             WHERE id = %s AND status IN ('PENDING', 'PROCESSING')
            """,
            (order_id,),
        )
        cur.execute(
            """
            INSERT INTO order_events
                (order_id, stage, detail, worker, event_key)
            VALUES (%s, 'READY', 'payment and inventory succeeded',
                    'coordinator', 'workflow.ready')
            ON CONFLICT DO NOTHING
            """,
            (order_id,),
        )
        return not row["ready_published"]


def mark_ready_published(order_id: str) -> None:
    with db.cursor() as cur:
        cur.execute(
            "UPDATE order_workflow SET ready_published = TRUE "
            "WHERE order_id = %s",
            (order_id,),
        )


def record_restaurant_confirmation(order_id: str, detail: str,
                                   worker: str) -> bool:
    """Confirm only a ready, non-failed order."""
    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE order_workflow
               SET restaurant_notified = TRUE
             WHERE order_id = %s
               AND payment_succeeded = TRUE
               AND inventory_reserved = TRUE
               AND failed_step IS NULL
               AND restaurant_notified = FALSE
            RETURNING order_id
            """,
            (order_id,),
        )
        if cur.fetchone() is None:
            return False
        cur.execute(
            "UPDATE orders SET status = 'CONFIRMED', updated_at = now() "
            "WHERE id = %s AND status <> 'FAILED'",
            (order_id,),
        )
        cur.execute(
            """
            INSERT INTO order_events
                (order_id, stage, detail, worker, event_key)
            VALUES (%s, 'RESTAURANT_NOTIFIED', %s, %s,
                    'step.restaurant.succeeded')
            ON CONFLICT DO NOTHING
            """,
            (order_id, detail, worker),
        )
        cur.execute(
            """
            INSERT INTO order_events
                (order_id, stage, detail, worker, event_key)
            VALUES (%s, 'CONFIRMED', 'restaurant accepted ticket', %s,
                    'workflow.confirmed')
            ON CONFLICT DO NOTHING
            """,
            (order_id, worker),
        )
        return True


def complete_order(order_id: str, message: str, worker: str) -> bool:
    """Complete only a restaurant-confirmed, non-failed order."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT restaurant_notified, failed_step
              FROM order_workflow
             WHERE order_id = %s
             FOR UPDATE
            """,
            (order_id,),
        )
        state = cur.fetchone()
        if (state is None or state["failed_step"] is not None
                or not state["restaurant_notified"]):
            return False
        cur.execute(
            """
            INSERT INTO order_events
                (order_id, stage, detail, worker, event_key)
            VALUES (%s, 'NOTIFIED', %s, %s, 'notification.success')
            ON CONFLICT DO NOTHING
            """,
            (order_id, message, worker),
        )
        if cur.rowcount != 1:
            return False
        cur.execute(
            "UPDATE orders SET status = 'COMPLETED', updated_at = now() "
            "WHERE id = %s AND status <> 'FAILED'",
            (order_id,),
        )
        cur.execute(
            """
            INSERT INTO order_events
                (order_id, stage, detail, worker, event_key)
            VALUES (%s, 'COMPLETED', 'customer notified', %s,
                    'workflow.completed')
            ON CONFLICT DO NOTHING
            """,
            (order_id, worker),
        )
        return True


def fail_workflow(order_id: str, failed_step: str, reason: str) -> bool:
    """Fail once, compensate all completed critical steps, and gate success."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT payment_succeeded, inventory_reserved, restaurant_notified,
                   ready_published, failure_published, failed_step
              FROM order_workflow
             WHERE order_id = %s
             FOR UPDATE
            """,
            (order_id,),
        )
        row = cur.fetchone()
        if row is None:
            return False
        # An ambiguous publisher retry must not reverse an outcome already
        # accepted by the next stage of the workflow.
        if (failed_step in {"payment", "inventory"} and row["ready_published"]):
            return False
        if failed_step == "restaurant" and row["restaurant_notified"]:
            return False
        cur.execute(
            """
            UPDATE order_workflow
               SET failed_step = COALESCE(failed_step, %s)
             WHERE order_id = %s
            """,
            (failed_step, order_id),
        )
        cur.execute(
            "UPDATE orders SET status = 'FAILED', updated_at = now() "
            "WHERE id = %s",
            (order_id,),
        )
        cur.execute(
            """
            INSERT INTO order_events
                (order_id, stage, detail, worker, event_key)
            VALUES (%s, 'FAILED', %s, 'coordinator', 'workflow.failed')
            ON CONFLICT DO NOTHING
            """,
            (order_id, f"{failed_step}: {reason}"),
        )
        _record_compensations(cur, order_id)
        return not row["failure_published"]


def _record_compensations(cur, order_id: str) -> None:
    cur.execute(
        "SELECT payment_succeeded, inventory_reserved FROM order_workflow "
        "WHERE order_id = %s",
        (order_id,),
    )
    state = cur.fetchone()
    if state and state["payment_succeeded"]:
        cur.execute(
            """
            INSERT INTO order_events
                (order_id, stage, detail, worker, event_key)
            VALUES (%s, 'PAYMENT_REFUNDED', 'simulated automatic refund',
                    'coordinator', 'compensation.payment_refunded')
            ON CONFLICT DO NOTHING
            """,
            (order_id,),
        )
    if state and state["inventory_reserved"]:
        cur.execute(
            """
            INSERT INTO order_events
                (order_id, stage, detail, worker, event_key)
            VALUES (%s, 'INVENTORY_RELEASED', 'simulated reservation release',
                    'coordinator', 'compensation.inventory_released')
            ON CONFLICT DO NOTHING
            """,
            (order_id,),
        )


def mark_failure_published(order_id: str) -> None:
    with db.cursor() as cur:
        cur.execute(
            "UPDATE order_workflow SET failure_published = TRUE "
            "WHERE order_id = %s",
            (order_id,),
        )


def get_order(order_id: str) -> dict | None:
    with db.cursor(commit=False) as cur:
        cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
        order = cur.fetchone()
        if order is None:
            return None
        cur.execute(
            """
            SELECT stage, detail, worker, at
              FROM order_events
             WHERE order_id = %s
             ORDER BY id
            """,
            (order_id,),
        )
        events = cur.fetchall()

    out = dict(order)
    out["total"] = float(out["total"])
    out["created_at"] = out["created_at"].isoformat()
    out["updated_at"] = out["updated_at"].isoformat()
    out["timeline"] = [
        {**dict(e), "at": e["at"].isoformat()} for e in events
    ]
    return out


def counts_by_status() -> dict[str, int]:
    with db.cursor(commit=False) as cur:
        cur.execute("SELECT status, COUNT(*) AS n FROM orders GROUP BY status")
        return {r["status"]: r["n"] for r in cur.fetchall()}


def truncate_all() -> None:
    """Used only by scripts/reset.py before a rehearsal."""
    with db.cursor() as cur:
        cur.execute("TRUNCATE order_events, order_workflow, orders")
