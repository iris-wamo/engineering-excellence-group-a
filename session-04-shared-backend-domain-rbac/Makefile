.PHONY: install hooks lint lint-fix format typecheck type-check test pre-commit precommit run migrate quality docker-up docker-down docker-test docker-logs docker-migrate

install:
	uv sync

hooks:
	uv run pre-commit install

lint:
	uv run ruff check .

lint-fix:
	uv run ruff check --fix .

format:
	uv run ruff format .

type-check:
	uv run mypy app

test:
	uv run pytest -v

precommit:
	uv run pre-commit run --all-files

run:
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

migrate:
	uv run alembic upgrade head

migrate-next:
	uv run alembic upgrade +1

migrate-previous:
	uv run alembic downgrade -1

migrate-base:
	uv run alembic downgrade base

seed:
	uv run python -m seeds.run

demo-assignment:
	uv run python -m scripts.demo_transaction_safe_assignment

migration-test:
	uv run alembic downgrade base
	uv run alembic upgrade +1
	uv run python -m seeds.run
	uv run alembic upgrade head

quality:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy app
	uv run pytest

docker-up:
	docker compose up --build

docker-down:
	docker compose down

docker-test:
	docker compose --profile test run --rm test

docker-logs:
	docker compose logs -f api postgres

docker-migrate:
	docker compose exec api uv run alembic upgrade head