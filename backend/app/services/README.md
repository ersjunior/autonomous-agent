# Services

Regra de negócio da API. As rotas (`app/api/v1/`) delegam aqui; estes serviços usam os modelos (`app/models/`) e, quando preciso, a IA em `agents/`.

## Grupos principais

| Tema | Serviços (exemplos) |
|---|---|
| **Identidade** | `agent_identity.py`, `user_identity.py`, `agent_context.py`, `tenant_resolution.py` |
| **Base de conhecimento (RAG)** | `kb_text_extract.py` (`.txt`/`.pdf`/`.docx`), `kb_chunking.py`, `kb_storage.py` |
| **Acionamento (ATIVO)** | `activation_service.py`, `activation_slots.py`, `activation_cadence.py`, `activation_history.py`, `receptive_window.py` |
| **Capacidade** | `capacity_service.py`, `capacity_estimate.py`, `capacity_analysis.py`, `queue_metrics.py` |
| **Fila receptiva** | `receptive_queue.py`, `queue_entry_service.py`, `inbound_attendance.py` |
| **Handoff humano** | `human_handoff.py` |
| **Tabulação** | `tabulacao_mapping.py`, `tabulacao_assignment.py`, `devolutiva.py` |
| **WhatsApp** | `whatsapp_outbound.py`, `whatsapp_delivery.py`, `contact_normalization.py` |
| **Voz** | `voice_turn_processor.py`, `voice_turn_state.py`, `voice_call_state.py`, `voice_call_finalize.py`, `voice_audio.py`, `voice_cached_audio.py`, `voice_sample.py` |
| **Métricas/Dashboard** | `metrics.py`, `dashboard_metrics.py`, `attendance_history.py` |
| **Configurações dinâmicas** | `settings_service.py`, `settings_schema.py`, `settings_sync.py` |
| **Leads** | `csv_import.py` |
| **Túnel** | `tunnel_status.py` |

## Padrão

Serviços são, em geral, funções/classes sem estado HTTP — recebem sessão de banco e dados validados, retornam dados de domínio. Isso mantém as rotas finas e a regra testável (ver `backend/tests/`).
