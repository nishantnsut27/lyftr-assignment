FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.9.10 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

FROM python:3.12-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LITELLM_LOCAL_MODEL_COST_MAP=True \
    DATABASE_URL=sqlite:////data/app.db \
    LLM_CACHE_DIR=/data/llm-cache \
    PORT=8000
RUN useradd --create-home --uid 10001 chatbot && mkdir /data && chown chatbot:chatbot /data
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --chown=chatbot:chatbot app ./app
USER chatbot
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/health',timeout=4)"
CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-access-log"]
