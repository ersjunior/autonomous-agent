# Roadmap e pendências conhecidas

Itens em aberto, funcionalidades parcialmente implementadas e trabalhos futuros. Esta lista reflete o estado atual do código e serve de guia para a evolução do sistema.

## Voz

| Item | Estado | Observação |
|---|---|---|
| Inbound de voz ao vivo | Parcial | O manipulador de chamada e o STT (faster-whisper) existem, mas não estão conectados ao Twilio Media Streams (transcrição bidirecional em tempo real) |
| Abandono real da fila de voz | Estrutural | O sweep de abandono existe, mas sem inbound de voz ao vivo a taxa fica próxima de zero na prática |

## Discagem e telefonia

| Item | Estado | Observação |
|---|---|---|
| Discador SIP próprio | Futuro | Hoje a telefonia usa Twilio (MVP); um discador SIP próprio é citado como trabalho futuro |
| Tabulação SIP automática | Parcial | A função de aplicar tabulação a partir de um código SIP está pronta, mas falta o callback de status da Twilio (StatusCallback) para acioná-la automaticamente |
| Callbacks de status da Twilio | Pendente | Eventos de entrega/falha de chamada e mensagem ainda não estão conectados |

## Agentes (workers dedicados)

Há stubs previstos no código para componentes que hoje são tratados de forma embutida:

| Componente | Estado |
|---|---|
| Agente de escalonamento dedicado | TODO (`agents/workers/escalation_agent.py`) |
| Agente de memória dedicado | TODO (`agents/workers/memory_agent.py`) |

## Tools (ferramentas do agente)

| Ferramenta | Estado |
|---|---|
| Integração com CRM | TODO (`agents/tools/crm_tool.py`) |
| Integração com calendário | TODO (`agents/tools/calendar_tool.py`) |

## Infraestrutura

| Item | Estado | Observação |
|---|---|---|
| GPU opcional para faster-whisper e Coqui | Futuro | Hoje rodam em CPU; há pontos no compose preparados para GPU |
| Módulos Terraform | TODO | Estrutura de IaC com placeholders |
| Guias de deploy em nuvem (AWS/Azure/GCP) | TODO | Documentação de deploy em nuvem ainda é placeholder |

## Concluído recentemente

Para referência, alguns marcos já entregues:

- **Validação do TTS Coqui (português):** pipeline outbound validado de ponta a ponta. Correções aplicadas — voz de referência ajustada para o formato ideal do XTTS-v2 (mono, 24 kHz, normalizada), resolvendo o timbre robótico; confirmado que a pronúncia correta depende dos acentos no texto enviado ao modelo; e o `COQUI_BASE_URL` passou a apontar para a porta interna correta do Docker. A geração de áudio em português está funcional no fluxo real (incluindo a compressão de telefonia).
- **Remoção do canal de vídeo:** o sistema foi consolidado em três canais (Telegram, WhatsApp, Voz); a stack de avatar (SadTalker/D-ID) foi removida, liberando GPU, e o valor correspondente foi retirado do enum de canais no banco.
- **URL pública fixa:** túnel Cloudflare em modo `named` com domínio próprio, eliminando a necessidade de reconfigurar webhooks a cada reinício.
- **Indicador "digitando...":** implementado para Telegram e WhatsApp.
- **Calibração do escalonamento:** ajuste do limiar de confiança para reduzir escaladas indevidas em mensagens curtas.
- **Agente neutro:** reforço no prompt padrão para o agente não inventar identidade quando não há base de conhecimento cadastrada.

Para o checklist operacional de demonstração, veja [CHECKLIST_DEMO.md](CHECKLIST_DEMO.md).
