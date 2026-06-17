# Diagrams

Diagramas de arquitetura do projeto em **Mermaid** (renderizam no GitHub, no Cursor e em visualizadores Markdown compatíveis).

| Diagrama | Onde está |
|---|---|
| Arquitetura de alto nível | [`docs/arquitetura.md`](../arquitetura.md#diagrama-alto-nível) |
| Componentes e fluxos inbound/outbound | [`docs/documentacao.md`](../documentacao.md) §2 |
| Grafo LangGraph, RAG e camadas de prompt | [`docs/agentes.md`](../agentes.md) |
| Fluxos por canal (WhatsApp, Telegram, Voz) | [`docs/canais.md`](../canais.md) |
| READMEs de `agents/channels/` | `whatsapp/`, `telegram/`, `voice/`, `README.md` |
| Grafo do orchestrator | [`agents/orchestrator/README.md`](../../../agents/orchestrator/README.md) |

## Regras para Mermaid neste projeto

- Em **sequenceDiagram**, não use `;` no texto das mensagens (o ponto-e-vírgula encerra a instrução no parser).
- Evite caracteres especiais (`→`, aspas aninhadas) nos rótulos — prefira texto simples.
- Use `subgraph id [Titulo]` para compatibilidade entre renderizadores.

## Capturas para apresentação

Capturas estáticas (ex.: `diagrama-grafo.png`) usadas na defesa ficam em [`docs/demo-assets/`](../demo-assets/README.md) e **não** são versionadas (`.gitignore`).
