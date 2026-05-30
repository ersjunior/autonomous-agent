# Canal Telegram

Integração do bot Telegram com o orquestrador LangGraph via `TelegramHandler`.

## Obter o token no BotFather

1. Abra o Telegram e busque [@BotFather](https://t.me/BotFather).
2. Envie `/newbot` e siga as instruções (nome e username do bot).
3. Ao final, o BotFather envia uma mensagem com o token no formato:

   ```
   123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   ```

4. Guarde esse valor e **revogue/regenere** no BotFather se ele vazar. Para bots já existentes, use `/mybots` → selecione o bot → **API Token**.

## Configurar `TELEGRAM_BOT_TOKEN`

Defina a variável de ambiente no `.env` local (se ainda não existir, copie de `.env.example`):

```
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
```

O backend lê esse valor via `app.core.config.Settings.telegram_bot_token`.

## Docker Compose

Inclua `TELEGRAM_BOT_TOKEN` no `.env` usado pelo `docker compose`. O serviço backend recebe as variáveis do `.env` correspondente.

## Uso no código

```python
from app.core.config import settings
from agents.channels.telegram import TelegramHandler

handler = TelegramHandler(token=settings.telegram_bot_token)
handler.start()  # bloqueia enquanto o polling estiver ativo
```

Para encerrar a partir de outro contexto (por exemplo, após um sinal do sistema), chame `handler.stop()`.

## Executar o handler

Com `PYTHONPATH` apontando para a raiz do projeto e para `backend/`:

```bash
cd backend
python -c "from app.core.config import settings; from agents.channels.telegram import TelegramHandler; TelegramHandler(settings.telegram_bot_token).start()"
```

Envie uma mensagem de texto ao bot no Telegram; a resposta passa pelo grafo em `agents.orchestrator.graph`.
