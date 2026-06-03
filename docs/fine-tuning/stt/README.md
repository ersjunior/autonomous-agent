# Fine-tuning Whisper para domínio específico

Para STT local com **faster-whisper**, o fine-tuning do modelo Whisper melhora reconhecimento de jargão, nomes de produtos e sotaques regionais.

## Abordagem recomendada

1. Colete áudio rotulado (WAV 16 kHz mono) + transcrições corrigidas manualmente.
2. Use [Hugging Face Transformers](https://huggingface.co/docs/transformers/model_doc/whisper) com `Seq2SeqTrainer`.
3. Exporte checkpoints compatíveis com CTranslate2 (backend do faster-whisper) via `faster-whisper` / conversão CT2.

## Dataset

| Campo | Descrição |
|-------|-----------|
| `audio` | Caminho para `.wav` |
| `sentence` | Transcrição ground truth |
| `language` | `pt` |

Estrutura sugerida: `data/stt/train.jsonl` com uma linha JSON por amostra.

## Integração com este projeto

Após treinar, defina o modelo convertido no serviço Docker:

```env
STT_PROVIDER=faster_whisper
WHISPER_MODEL=seu-modelo-finetuned
```

O container `faster-whisper` sobe por padrão com `make up` e lê `WHISPER_MODEL` em `infra/docker/faster-whisper/app.py`. A porta no host é `WHISPER_PORT` (padrão `8001`; remapeie no `.env` se houver conflito).

## Referências

- [OpenAI Whisper fine-tuning guide](https://huggingface.co/blog/fine-tune-whisper)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
