#!/bin/sh
# Inicia Telegram polling — SOMENTE com TELEGRAM_MODE=polling (TUN-2).
set -eu

MODE="${TELEGRAM_MODE:-polling}"
if [ "$MODE" = "webhook" ]; then
  echo "[telegram-polling] ERRO: TELEGRAM_MODE=webhook — não inicie este serviço." >&2
  echo "[telegram-polling] Use webhook no backend ou mude TELEGRAM_MODE=polling." >&2
  exit 1
fi

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
  echo "[telegram-polling] TELEGRAM_BOT_TOKEN vazio — serviço encerrado." >&2
  exit 1
fi

echo "[telegram-polling] TELEGRAM_MODE=polling — iniciando run_polling..."
exec python -c "
from app.core.config import settings
from agents.channels.telegram import TelegramHandler
TelegramHandler(settings.telegram_bot_token).start()
"
