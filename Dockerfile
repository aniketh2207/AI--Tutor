# ==============================================================================
# MULTI-STAGE: Frontend build (Node) + Python deps + CPU-only runtime
# ==============================================================================

# Stage 1: Vite frontend → /frontend/dist (same-origin /api via empty base URL)
FROM node:20-alpine AS frontend

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# Empty string → browser calls /api on the same origin as the SPA
ENV VITE_API_BASE_URL=
RUN npm run build

# Stage 2: Python dependency builder
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Stage 3: Lightweight production runtime (serves API + SPA)
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app" \
    PORT=8080 \
    APP_ENV=production \
    DEBUG=false

WORKDIR /app

RUN groupadd --gid 10001 appgroup && \
    useradd --uid 10001 --gid appgroup --shell /bin/sh --create-home appuser

COPY --from=builder /opt/venv /opt/venv
COPY --from=frontend --chown=appuser:appgroup /frontend/dist /app/static
COPY --chown=appuser:appgroup backend /app/backend

USER appuser

EXPOSE 8080

CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
