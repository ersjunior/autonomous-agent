#!/bin/sh
# Inicia Telegram polling — SOMENTE com TELEGRAM_MODE=polling (TUN-2).
# Serviço opt-in: docker compose --profile telegram-polling up -d telegram-polling
set -eu

MODE="$(printf '%s' "${TELEGRAM_MODE:-polling}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"

if [ "$MODE" != "polling" ]; then
  echo "[telegram-polling] AVISO: TELEGRAM_MODE=${TELEGRAM_MODE:-<vazio>} — polling não iniciado." >&2
  echo "[telegram-polling] Em modo webhook use apenas o backend (setWebhook no startup)." >&2
  echo "[telegram-polling] Para polling: TELEGRAM_MODE=polling e --profile telegram-polling." >&2
  # exit 0 evita loop de restart (restart: unless-stopped) quando o profile é acionado por engano.
  exit 0
fi

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
  echo "[telegram-polling] TELEGRAM_BOT_TOKEN vazio — serviço encerrado." >&2
  exit 0
fi

echo "[telegram-polling] TELEGRAM_MODE=polling — iniciando run_polling..."
exec python -c "
from app.core.config import settings
from agents.channels.telegram import TelegramHandler
TelegramHandler(settings.telegram_bot_token).start()
"
