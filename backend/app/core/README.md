# Core

Configuração central, segurança, acesso a banco e utilitários de inicialização compartilhados por toda a aplicação.

## Arquivos

| Arquivo | Papel |
|---|---|
| `config.py` | `Settings` (Pydantic) — **defaults da stack OSS local** (Ollama/faster-whisper/Coqui, embeddings 768d); provedores e segredos vêm de env/`.env` |
| `database.py` | Engine async SQLAlchemy, sessões e pool |
| `security.py` | Hash de senha e emissão/validação de JWT |
| `authorization.py` | Regras de ownership/autorização entre recursos |
| `seed.py` | Seed do admin de desenvolvimento e dos agentes/canais padrão |
| `erlang.py` | Modelo **Erlang C** para dimensionamento de capacidade receptiva |
| `activation_window.py` / `activation_cadence_text.py` / `activation_defaults.py` | Janelas, cadência e defaults de acionamento (fuso de São Paulo) |
| `inactivity_text.py` | Mensagens de inatividade |
| `voice_silence_text.py` | Textos para silêncio em chamadas de voz |
| `telegram_setup.py` | Bootstrap do webhook/polling do Telegram |
| `tunnel_log.py` | Leitura/estado do log do túnel Cloudflare |

## Premissa de configuração

Os defaults de `config.py` apontam para a **stack OSS local** (sem chaves de API), alinhados com `docker-compose.yml` e `.env.example`. Plugar uma alternativa de nuvem (OpenAI/ElevenLabs) é só questão de variáveis de ambiente — ver [`docs/configuracao.md`](../../../../docs/configuracao.md).
