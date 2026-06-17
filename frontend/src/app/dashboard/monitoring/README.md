# Monitoring

Monitoramento de atendimentos **em tempo real** (`/dashboard/monitoring`). Conecta ao WebSocket do backend (`/api/v1/monitoring/ws`), alimentado pelo Redis pub/sub (`agent_events`).

## Eventos exibidos

- `intent_detected` — intenção identificada (com confiança e severidade).
- `response_sent` — resposta enviada pelo agente.
- `escalated` — atendimento encaminhado para humano.

Cada atendimento pode ser aberto em detalhe (`AttendanceConversationModal`) para ver a conversa completa. O cliente WebSocket fica em `src/lib/api-monitoring.ts`.
