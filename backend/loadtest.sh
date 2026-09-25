#!/usr/bin/env bash
# Нагрузочный замер через ApacheBench.  Использование:
#   backend/loadtest.sh [BASE_URL] [REQUESTS] [CONCURRENCY]
# По умолчанию http://localhost:8000, 20000 запросов, 64 соединения (keep-alive).
set -euo pipefail
BASE=${1:-http://localhost:8000}; N=${2:-20000}; C=${3:-64}
BODY=$(mktemp); trap 'rm -f "$BODY"' EXIT
echo '{"route":7,"granularity":"day","factors":{"weather":0.95},"rules":[{"start":"2025-12-25","end":"2025-12-31","factor":0.8}]}' > "$BODY"

run() {  # имя, аргументы ab...
  local name=$1; shift
  local out; out=$(ab -k -q -n "$N" -c "$C" "$@" 2>&1)
  printf '%-46s %6s rps  p50 %4s  p95 %4s  p99 %4s мс  ошибок %s  не-2xx %s\n' "$name" \
    "$(awk '/Requests per second/ {printf "%.0f", $4}' <<<"$out")" \
    "$(awk '/^ +50%/ {print $2}' <<<"$out")" "$(awk '/^ +95%/ {print $2}' <<<"$out")" "$(awk '/^ +99%/ {print $2}' <<<"$out")" \
    "$(awk '/^Failed requests/ {print $3}' <<<"$out")" "$(awk '/^Non-2xx/ {print $3}' <<<"$out" | head -1 | grep . || echo 0)"
}

run "GET /forecast (день, все маршруты)"        "$BASE/api/v1/forecast?granularity=day"
run "GET /forecast (час, 1 день, все)"          "$BASE/api/v1/forecast?start=2025-11-05&end=2025-11-05&granularity=hour"
run "GET /forecast (час, маршрут 7, 31 день)"   "$BASE/api/v1/forecast?route=7&start=2025-11-01&end=2025-12-01&granularity=hour"
run "GET /history (день, маршрут 7)"            "$BASE/api/v1/history?route=7&granularity=day"
run "GET /routes"                               "$BASE/api/v1/routes"
run "GET /export (CSV, весь прогноз)"           "$BASE/api/v1/export"
run "GET /stops/flow (маршрут 7)"               "$BASE/api/v1/stops/flow?route=7"
run "GET /stops/segments (маршрут 7)"           "$BASE/api/v1/stops/segments?route=7"
run "POST /forecast/adjusted (день, маршрут 7)" -p "$BODY" -T application/json "$BASE/api/v1/forecast/adjusted"
