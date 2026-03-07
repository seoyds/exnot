.PHONY: up down build restart logs logs-web logs-worker logs-beat \
       ps test lint format migrate migrate-new shell db-shell \
       clean rebuild up-infra up-app

# ---------------------------------------------------------------------------
# Docker Compose
# ---------------------------------------------------------------------------

up: ## Start all services
	docker compose up -d

down: ## Stop all services
	docker compose down

build: ## Build all images
	docker compose build

rebuild: ## Rebuild and restart all services (no cache)
	docker compose build --no-cache
	docker compose up -d

restart: ## Restart all services
	docker compose restart

up-infra: ## Start only infrastructure (db, redis, minio)
	docker compose up -d db redis minio

up-app: ## Start app services (web, worker, beat)
	docker compose up -d web worker beat

# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

logs: ## Tail logs for all services
	docker compose logs -f --tail=100

logs-web: ## Tail web service logs
	docker compose logs -f --tail=100 web

logs-worker: ## Tail worker service logs
	docker compose logs -f --tail=100 worker

logs-beat: ## Tail beat service logs
	docker compose logs -f --tail=100 beat

logs-flower: ## Tail flower service logs
	docker compose logs -f --tail=100 flower

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

ps: ## Show running containers
	docker compose ps

# ---------------------------------------------------------------------------
# Testing & Linting
# ---------------------------------------------------------------------------

test: ## Run all tests
	docker compose exec web pytest

test-unit: ## Run unit tests only
	docker compose exec web pytest tests/unit/ -v

test-integration: ## Run integration tests only
	docker compose exec web pytest -m integration -v

lint: ## Run ruff linter
	docker compose exec web ruff check src/ tests/

format: ## Run ruff formatter
	docker compose exec web ruff format src/ tests/

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

migrate: ## Run database migrations
	docker compose exec web alembic upgrade head

migrate-new: ## Create a new migration (usage: make migrate-new msg="description")
	docker compose exec web alembic revision --autogenerate -m "$(msg)"

migrate-history: ## Show migration history
	docker compose exec web alembic history --verbose

# ---------------------------------------------------------------------------
# Shells
# ---------------------------------------------------------------------------

shell: ## Open a bash shell in the web container
	docker compose exec web bash

db-shell: ## Open a psql shell in the database
	docker compose exec db psql -U exnot -d exnot

redis-shell: ## Open a redis-cli shell
	docker compose exec redis redis-cli

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean: ## Stop services and remove volumes
	docker compose down -v

prune: ## Remove dangling images and build cache
	docker image prune -f
	docker builder prune -f

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
