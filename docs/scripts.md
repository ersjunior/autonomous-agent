# Scripts de validação

A pasta `backend/scripts/` reúne scripts de validação ponta a ponta que exercitam fluxos completos do sistema (acionamento, fila receptiva, handoff, RAG, KB, tabulação, etc.). Diferente dos testes automatizados (pytest), são roteiros executáveis úteis para validar manualmente uma camada em um ambiente de pé.

## Execução

Com a stack rodando, execute dentro do container do backend:

```bash
docker exec autonomous-agent-backend python /workspace/backend/scripts/.py
```

## Catálogo

| Script | Propósito |
|---|---|
| `validate_layer_a_activation.py` | Camada A — parâmetros, settings de canal, start/stop de acionamento |
| `validate_layer_b_activation.py` | Camada B — janela de horário e scheduler |
| `validate_layer_c_activation.py` | Camada C — cadência, follow-up e quota horária |
| `validate_layer_d_activation.py` | Camada D — slots no Redis e fila de prioridade |
| `validate_layer_ra_receptive.py` | R-A — fila receptiva e capacidade global |
| `validate_layer_rb_queue.py` | R-B — entradas de fila e métricas de SLA |
| `validate_layer_rc_capacity.py` | R-C — estimativa, Erlang e outbound no teto de capacidade |
| `validate_receptive_b1.py` | B-1 — conduta receptiva, escalonamento e tabulação de escalada |
| `validate_human_mode_b2.py` | B-2 — modo humano no Redis (fluxo legado) |
| `validate_human_handoff_h1.py` | H-1 — notificação ao operador e link de contato |
| `validate_human_handoff_h2.py` | H-2 — ciclo assumir/finalizar/sweep do handoff |
| `validate_tabulacao_t2.py` | T-2 — tabulação por regra/IA e devolutiva |
| `validate_rag.py` | RAG — memória em pgvector e isolamento por `user_id` |
| `validate_kb_1.py` | KB-1 — ingestão assíncrona e chunking |
| `validate_kb_2.py` | KB-2 — recuperação semântica no grafo |
| `validate_phase4_routing.py` | Roteamento ACTIVE/RECEPTIVE (cenários A–E) |
| `validate_campaign_stop.py` | Parada de campanha e pausa das ativações |
| `validate_test_dispatch.py` | Disparo de teste ad-hoc (`/activation/test-dispatch`) |
| `validate_activation_history.py` | Histórico de acionamento e finalização |
| `validate_attendance_history.py` | Histórico de atendimentos no monitoramento |
| `validate_worker_fix.py` | Regressão do worker outbound e registro de interações |

Esses scripts complementam a suíte automatizada (veja [testes.md](testes.md)) e foram úteis para validar incrementalmente cada camada do sistema durante o desenvolvimento.
