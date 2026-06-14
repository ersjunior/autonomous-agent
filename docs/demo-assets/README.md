# Assets de fallback — apresentação (Plano B)

Esta pasta guarda **materiais locais** para a defesa do TCC, caso alguma demo ao vivo falhe (GPU, latência do Ollama, Twilio, etc.). Os binários **não** entram no Git — apenas este README.

## O que colocar aqui

| Arquivo sugerido | Uso |
|------------------|-----|
| `voz-demo.mp3` | Áudio gerado pelo teste de voz (Coqui) na aba Configurações → Áudio |
| `diagrama-grafo.png` | Captura do diagrama B (LangGraph) do README |
| `diagrama-rag.png` | Captura do diagrama D (memória/RAG) |
| `validate-rag-output.txt` | Saída de `backend/scripts/validate_rag.py` (similaridades + bloco RAG + vazamento) |
| `validate-phase4-routing-output.txt` | Saída de `backend/scripts/validate_phase4_routing.py` (cenários A–E com `OK=True`) |

## Como gerar antes da banca

1. Rodar `docs/SMOKE_TEST.md` até tudo verde.
2. Gravar/copiar os artefatos acima para esta pasta.
3. No dia da apresentação, seguir `docs/ROTEIRO_APRESENTACAO.md` — seção **Plano B**.

## Versionamento

- `*.mp3` e imagens grandes nesta pasta estão no `.gitignore`.
- Não commitar tokens, `.env` nem dados reais de clientes.
