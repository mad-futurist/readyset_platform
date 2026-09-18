FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.16 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY app ./app
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
RUN groupadd --system readyset && useradd --system --gid readyset --home-dir /nonexistent readyset
WORKDIR /app
COPY --from=build --chown=readyset:readyset /app/.venv /app/.venv
COPY --chown=readyset:readyset app ./app
COPY --chown=readyset:readyset alembic.ini ./
COPY --chown=readyset:readyset alembic ./alembic
USER readyset
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
