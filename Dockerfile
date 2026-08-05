FROM cgr.dev/chainguard/node:latest-dev AS frontend-build
USER root
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-alpine AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/static
WORKDIR /app/backend
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=frontend-build /build/frontend/dist /app/static
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/api/health', timeout=2)"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]