# Multi-stage: compile wheels with build tools; runtime image has no build-essential (much smaller).
# Stay on Debian slim — Alpine/musl breaks many scientific wheels (torch, onnxruntime, chromadb).
FROM python:3.12-slim-bookworm AS builder

ARG REQUIREMENTS_FILE=both

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements-document.txt requirements-chat.txt .

RUN set -eux; \
    pip install --no-cache-dir -U pip setuptools wheel; \
    if [ "${REQUIREMENTS_FILE}" = "both" ]; then \
      pip install --no-cache-dir -r requirements-document.txt -r requirements-chat.txt; \
    else \
      pip install --no-cache-dir -r "${REQUIREMENTS_FILE}"; \
    fi

FROM python:3.12-slim-bookworm

WORKDIR /app

# Runtime libs for manylinux wheels (OpenMP — used by torch / numpy / onnxruntime paths).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH"
COPY --from=builder /opt/venv /opt/venv

COPY app ./app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Default: full backend (both requirement files). Compose overrides per service.
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
