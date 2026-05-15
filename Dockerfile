FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /app/requirements.txt

# ── Pre-warm tiktoken encoding files into the image ─────────────────────────
# litellm.token_counter() internally calls tiktoken, which downloads encoding
# files from openaipublic.blob.core.windows.net on first use. We pre-download
# them here so the runtime container never needs outbound internet access.
ENV TIKTOKEN_CACHE_DIR=/root/.tiktoken
RUN python -c "import tiktoken; [tiktoken.get_encoding(n) for n in ['cl100k_base','o200k_base','p50k_base']]; print('tiktoken warm-up complete.')"

COPY . /app

EXPOSE 22223

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "22223"]

