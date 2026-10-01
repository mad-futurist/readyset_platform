FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.16 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy TIKTOKEN_CACHE_DIR=/app/tokenizer-cache
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY app ./app
ADD --checksum=sha256:223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7 https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken /app/tokenizer-cache/9b5ad71b2ce5302211f9c61530b329a4922fc6a4
ADD --checksum=sha256:446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken /app/tokenizer-cache/fb374d419588a4632f3f557e76b4b70aebbca790
RUN uv sync --frozen --no-dev --no-editable && .venv/bin/python -c "import tiktoken; tiktoken.get_encoding('cl100k_base'); tiktoken.get_encoding('o200k_base')"

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH" TIKTOKEN_CACHE_DIR=/app/tokenizer-cache
RUN groupadd --system readyset && useradd --system --gid readyset --home-dir /nonexistent readyset
WORKDIR /app
COPY --from=build --chown=readyset:readyset /app/.venv /app/.venv
COPY --from=build --chown=readyset:readyset /app/tokenizer-cache /app/tokenizer-cache
COPY --chown=readyset:readyset app ./app
COPY --chown=readyset:readyset alembic.ini ./
COPY --chown=readyset:readyset alembic ./alembic
USER readyset
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
