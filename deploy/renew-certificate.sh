#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR=/opt/hackathon-transport-moskvy
CERT_FILE="$APP_DIR/certs/letsencrypt/live/mos.fotur.tech/fullchain.pem"
PIGMENT_COMPOSE=/opt/pigment/docker-compose.production.yml
TRAM_COMPOSE="$APP_DIR/docker-compose.server.yml"

# Renew only when the current certificate has 30 days or less remaining.
if [ -f "$CERT_FILE" ] && openssl x509 -checkend 2592000 -noout -in "$CERT_FILE" >/dev/null 2>&1; then
  exit 0
fi

restore_services() {
  docker compose -f "$PIGMENT_COMPOSE" up -d caddy
  docker compose -p moskvy-tram -f "$TRAM_COMPOSE" up -d --no-deps ingress
}
trap restore_services EXIT

docker compose -f "$PIGMENT_COMPOSE" stop caddy
docker run --rm -p 80:80 \
  -v "$APP_DIR/certs/letsencrypt:/etc/letsencrypt" \
  certbot/certbot renew --standalone --preferred-challenges http --quiet
