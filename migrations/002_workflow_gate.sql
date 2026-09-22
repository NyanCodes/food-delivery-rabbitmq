-- Durable, idempotent state for joining payment and inventory outcomes.

ALTER TABLE order_events ADD COLUMN event_key TEXT;

CREATE UNIQUE INDEX order_events_unique_key_idx
    ON order_events (order_id, event_key)
    WHERE event_key IS NOT NULL;

CREATE TABLE order_workflow (
    order_id             TEXT PRIMARY KEY REFERENCES orders (id) ON DELETE CASCADE,
    payment_succeeded    BOOLEAN NOT NULL DEFAULT FALSE,
    inventory_reserved   BOOLEAN NOT NULL DEFAULT FALSE,
    restaurant_notified  BOOLEAN NOT NULL DEFAULT FALSE,
    ready_published      BOOLEAN NOT NULL DEFAULT FALSE,
    failure_published    BOOLEAN NOT NULL DEFAULT FALSE,
    failed_step          TEXT
);

-- Existing orders predate workflow coordination. Preserve them for display;
-- only newly created orders participate in the gated workflow.
