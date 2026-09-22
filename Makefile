PYTHON ?= python3

.PHONY: up ps down nuke infra migrate api payment inventory coordinator restaurant notify run reset health logs logs-workers demo chaos fail scale test build config

up:
	docker compose up -d --build

ps:
	docker compose ps

down:
	docker compose down

nuke:
	docker compose down -v

infra:
	docker compose up -d rabbitmq postgres

migrate:
	$(PYTHON) -m scripts.migrate

api:
	uvicorn app.api:app --reload --port 8000

payment:
	$(PYTHON) -m app.workers.payment_worker

inventory:
	$(PYTHON) -m app.workers.inventory_worker

coordinator:
	$(PYTHON) -m app.workers.coordinator_worker

restaurant:
	$(PYTHON) -m app.workers.restaurant_worker

notify:
	$(PYTHON) -m app.workers.notification_worker

run:
	./scripts/run_all.sh

reset:
	docker compose exec api python -m scripts.reset

health:
	@curl -fsS http://localhost:8000/health && echo

logs:
	docker compose logs -f

logs-workers:
	docker compose logs -f payment-worker inventory-worker coordinator-worker restaurant-worker notification-worker

demo:
	docker compose exec api python demo/load_test.py 30 6

chaos:
	docker compose exec api python demo/chaos_demo.py

fail:
	@docker compose stop payment-worker; trap 'docker compose start payment-worker >/dev/null' EXIT; docker compose exec api python -m demo.failure_demo

scale:
	docker compose up -d --scale payment-worker=3 payment-worker

test:
	docker compose exec -e INTEGRATION=1 api pytest -v

build:
	docker build -t food-delivery-rabbitmq:local .

config:
	docker compose config --quiet
