# Multi-stage image for the PR Review Assistant.
#
# Stage 1 (node:20-alpine) builds the React SPA; stage 2 (python:3.11-slim)
# runs the FastAPI backend and serves the built SPA from /app/backend/static
# (the app mounts it at "/" with an index.html fallback when STATIC_DIR
# exists).  SQLite data is expected on the /app/data volume.

# ---------- Stage 1: build the frontend ----------
FROM node:20-alpine AS frontend-build
WORKDIR /build/frontend
# Install dependencies first so this layer only rebuilds on lockfile changes.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: Python runtime (API + SPA) ----------
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

# Runtime dependencies first (cache-friendly).
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Application code and the built SPA.
COPY backend/app ./backend/app
COPY --from=frontend-build /build/frontend/dist ./backend/static

# Container defaults: SPA served from the copied dist; SQLite on /app/data
# (mount a volume there - see docker-compose.yml / the Makefile run target).
ENV STATIC_DIR=/app/backend/static \
    DATABASE_PATH=/app/data/analyses.db

WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
