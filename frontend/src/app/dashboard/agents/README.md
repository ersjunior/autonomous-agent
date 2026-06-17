# Agents

Configuração de agentes de IA (`/dashboard/agents`). Permite criar/editar agentes e definir sua **identidade institucional** e personalidade.

## O que se configura

- **Identidade institucional** (override por agente): nome, tom e contexto de negócio injetados no prompt do LLM.
- **Modo de operação:** ATIVO (campanhas outbound) ou RECEPTIVO (responde inbound).
- Personalidade e parâmetros do agente.

A identidade tem duas camadas — **workspace** (em Configurações) + **override por agente** (aqui). A identidade define *quem* o agente é; a base de conhecimento (KB) guarda os *fatos*. Ver [`docs/agentes.md`](../../../../../docs/agentes.md).
