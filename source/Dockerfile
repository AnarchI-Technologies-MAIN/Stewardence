# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.12.9 AS uv
FROM python:3.14.7-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src:/app \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY --from=uv /uv /bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-default-groups --no-install-project

COPY manage.py ./
COPY apps ./apps
COPY collector ./collector
COPY src ./src
COPY templates ./templates
COPY static ./static

RUN DJANGO_SETTINGS_MODULE=agentledger.settings.production \
    DJANGO_SECRET_KEY=build-only-staticfiles-secret-with-no-runtime-authority-123456 \
    DATABASE_URL=postgresql://build:build@localhost/build \
    ALLOWED_HOSTS=localhost \
    CSRF_TRUSTED_ORIGINS=https://localhost \
    REPORTS_BUCKET_NAME=build \
    REPORTS_BUCKET_ENDPOINT=https://localhost \
    REPORTS_BUCKET_ACCESS_KEY_ID=build \
    REPORTS_BUCKET_SECRET_ACCESS_KEY=build \
    REPORT_RENDERER_URL=http://localhost \
    .venv/bin/python manage.py collectstatic --no-input

FROM python:3.14.7-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src:/app

RUN groupadd --gid 10001 agentledger \
    && useradd --uid 10001 --gid agentledger --home-dir /app --no-create-home agentledger

WORKDIR /app
COPY --from=builder --chown=agentledger:agentledger /app /app
USER agentledger

EXPOSE 8000

CMD [".venv/bin/gunicorn", "--config", "src/agentledger/gunicorn.conf.py", "agentledger.wsgi:application"]
