#!/bin/sh
# Cloudflare Tunnel — TUN-1
#
# TUNNEL_MODE=temporary (default): quick tunnel → captura URL *.trycloudflare.com
#   e grava em TUNNEL_URL_FILE para o backend resolver PUBLIC_BASE_URL.
# TUNNEL_MODE=named: tunnel fixo via CLOUDFLARE_TUNNEL_TOKEN (PUBLIC_BASE_URL no .env).
#
set -eu

TUNNEL_URL_FILE="${TUNNEL_URL_FILE:-/shared/tunnel_url.txt}"
TUNNEL_MODE="${TUNNEL_MODE:-temporary}"
BACKEND_URL="${CLOUDFLARED_BACKEND_URL:-http://backend:8000}"
URL_REGEX='https://[a-zA-Z0-9-]+\.trycloudflare\.com'

mkdir -p "$(dirname "$TUNNEL_URL_FILE")"

capture_url_from_line() {
  line="$1"
  # BusyBox/Alpine grep -oE
  url=$(printf '%s\n' "$line" | grep -oE "$URL_REGEX" 2>/dev/null | head -1 || true)
  if [ -n "$url" ]; then
    current=""
    if [ -f "$TUNNEL_URL_FILE" ]; then
      current=$(cat "$TUNNEL_URL_FILE" 2>/dev/null || true)
    fi
    if [ "$current" != "$url" ]; then
      printf '%s' "$url" > "$TUNNEL_URL_FILE"
      echo "[cloudflared] URL pública gravada em ${TUNNEL_URL_FILE}: ${url}"
    fi
  fi
}

run_named() {
  if [ -z "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
    echo "[cloudflared] ERRO: CLOUDFLARE_TUNNEL_TOKEN obrigatório para TUNNEL_MODE=named" >&2
    exit 1
  fi
  echo "[cloudflared] Modo named — use PUBLIC_BASE_URL fixa do .env (sem captura de URL)"
  exec cloudflared --no-autoupdate tunnel run --token "$CLOUDFLARE_TUNNEL_TOKEN"
}

run_temporary() {
  echo "[cloudflared] Modo temporary — quick tunnel para ${BACKEND_URL}"
  rm -f "$TUNNEL_URL_FILE"

  # cloudflared imprime a URL em stderr; merge com stdout para parse + log.
  cloudflared tunnel --url "$BACKEND_URL" --no-autoupdate 2>&1 | while IFS= read -r line; do
    printf '%s\n' "$line"
    capture_url_from_line "$line"
  done
}

case "$TUNNEL_MODE" in
  named)
    run_named
    ;;
  temporary|"")
    run_temporary
    ;;
  *)
    echo "[cloudflared] ERRO: TUNNEL_MODE inválido: ${TUNNEL_MODE} (use temporary ou named)" >&2
    exit 1
    ;;
esac
