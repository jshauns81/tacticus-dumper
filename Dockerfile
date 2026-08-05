# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    HOST=0.0.0.0 \
    PORT=5000 \
    DATA_DIR=/data \
    TZ=America/Chicago

WORKDIR /app

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /data/dumps \
    && chown -R app:app /app /data

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app.py ./

USER app

EXPOSE 5000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.environ.get('PORT', '5000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=3).read()"

CMD ["sh", "-c", "exec gunicorn -w ${GUNICORN_WORKERS:-2} -b ${HOST:-0.0.0.0}:${PORT:-5000} --timeout ${GUNICORN_TIMEOUT:-60} app:app"]
