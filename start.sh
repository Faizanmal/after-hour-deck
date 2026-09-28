#!/bin/sh
set -eu

/opt/venv/bin/uvicorn app.main:app --app-dir /app/backend --host 127.0.0.1 --port 8000 &

ok=0
i=0
while [ "$i" -lt 30 ]; do
  if /opt/venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" >/dev/null 2>&1; then
    ok=1
    break
  fi
  i=$((i + 1))
  sleep 1
done

if [ "$ok" -ne 1 ]; then
  echo "API failed to start" >&2
  exit 1
fi

cd /app/frontend
exec npx next start --hostname 0.0.0.0 --port "${PORT:-8080}"
