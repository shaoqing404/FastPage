FROM python:3.12-slim

ARG UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
ARG TIKTOKEN_PREWARM=true

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX} \
    PATH="/app/.venv/bin:/root/.local/bin:${PATH}" \
    DATA_DIR=/var/lib/pageindex/data \
    LOG_DIR=/var/log/pageindex \
    ENABLE_LITELLM=false

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh

COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-install-project
ENV UV_PYTHON=/app/.venv/bin/python

# ── Pre-warm tiktoken encoding files into the image ─────────────────────────
# litellm.token_counter() internally calls tiktoken, which downloads encoding
# files from openaipublic.blob.core.windows.net on first use. We pre-download
# them here so the runtime container never needs outbound internet access.
ENV TIKTOKEN_CACHE_DIR=/root/.tiktoken
RUN if [ "${TIKTOKEN_PREWARM}" = "true" ]; then \
      /app/.venv/bin/python -c "import tiktoken; [tiktoken.get_encoding(n) for n in ['cl100k_base','o200k_base','p50k_base']]; print('tiktoken warm-up complete.')"; \
    else \
      echo "Skipping tiktoken warm-up."; \
    fi

COPY . /app
RUN mkdir -p "${DATA_DIR}" "${LOG_DIR}" \
    && chmod -R 0775 /var/lib/pageindex /var/log/pageindex

EXPOSE 22223

CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "22223"]
