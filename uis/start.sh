#!/bin/sh
# Arranca las dos apps Next.js del contenedor de interfaces en modo desarrollo.
# Si una de las dos se detiene, el script sale y Docker lo refleja en el estado
# del contenedor en lugar de dejar una app caída en silencio.
set -eu

cd /app/uis

(cd website && exec ./node_modules/.bin/next dev --hostname 0.0.0.0 --port 3000) &
website_pid=$!

(cd backoffice && exec ./node_modules/.bin/next dev --hostname 0.0.0.0 --port 3001) &
backoffice_pid=$!

trap 'kill "$website_pid" "$backoffice_pid" 2>/dev/null' INT TERM

while kill -0 "$website_pid" 2>/dev/null && kill -0 "$backoffice_pid" 2>/dev/null; do
  sleep 2
done

echo "start.sh: una de las apps Next.js se ha detenido; parando el contenedor" >&2
kill "$website_pid" "$backoffice_pid" 2>/dev/null || true
exit 1
