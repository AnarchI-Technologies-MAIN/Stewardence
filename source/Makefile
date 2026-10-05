.PHONY: bootstrap test lint run migrate

bootstrap:
	uv sync --frozen

test:
	uv run --no-sync pytest --cov --cov-report=term-missing

lint:
	uv run --no-sync ruff check .
	uv run --no-sync ruff format --check .

run:
	uv run --no-sync python manage.py runserver

migrate:
	uv run --no-sync python manage.py migrate
