FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

# Install playwright browsers
RUN playwright install --with-deps chromium

COPY . .
RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["uvicorn", "exnot.api.app:app", "--host", "0.0.0.0", "--port", "8000"]


# === Docling stage: adds CPU-only PyTorch + Docling for deep learning table extraction ===
# Build with: DOCKER_BUILD_TARGET=docling docker compose build
FROM base AS docling

RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    "docling>=2.31.0" "docling-core>=2.0.0"
