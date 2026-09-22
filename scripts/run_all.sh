#!/usr/bin/env sh
set -eu

python -m scripts.migrate
python -m app.workers.payment_worker & payment_pid=$!
python -m app.workers.restaurant_worker & restaurant_pid=$!
python -m app.workers.notification_worker & notification_pid=$!
uvicorn app.api:app --host 0.0.0.0 --port 8000 & api_pid=$!

cleanup() {
  kill "$api_pid" "$payment_pid" "$restaurant_pid" "$notification_pid" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM
wait "$api_pid"
