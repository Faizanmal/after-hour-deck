FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

WORKDIR /app/frontend
RUN npm ci && npm run build

ENV PATH="/opt/venv/bin:$PATH" \
    PUBLIC_DEMO=1 \
    DATABASE_URL="" \
    SQLITE_URL=sqlite:////data/clinic.db \
    PORT=8080

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8080

CMD ["/app/start.sh"]
