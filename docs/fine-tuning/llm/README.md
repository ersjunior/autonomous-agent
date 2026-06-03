# Fine-tuning LoRA — LLaMA 3.1 para atendimento ao cliente

Este guia descreve como adaptar um modelo open source (LLaMA 3.1) ao domínio de **atendimento ao cliente** usando [Unsloth](https://github.com/unslothai/unsloth) e carregar o resultado no **Ollama**.

## Pré-requisitos

- GPU NVIDIA com ≥ 16 GB VRAM (recomendado para LLaMA 3.1 8B)
- Python 3.10+
- Dataset no formato ShareGPT (ver [dataset_format.md](./dataset_format.md))

## 1. Ambiente

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
pip install datasets transformers trl peft accelerate bitsandbytes
```

## 2. Dataset ShareGPT

Converta seu JSON para o formato esperado pelo `datasets`:

```python
from datasets import load_dataset

dataset = load_dataset("json", data_files="data/customer_support_sharegpt.json", split="train")
```

Cada linha deve seguir o schema documentado em [dataset_format.md](./dataset_format.md).

## 3. Script de treinamento (LoRA)

Exemplo mínimo com Unsloth + LLaMA 3.1 8B Instruct:

```python
from unsloth import FastLanguageModel
from trl import SFTTrainer
from transformers import TrainingArguments

MAX_SEQ_LENGTH = 2048
LORA_R = 16

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/Meta-Llama-3.1-8B-Instruct",
    max_seq_length=MAX_SEQ_LENGTH,
    load_in_4bit=True,
)

model = FastLanguageModel.get_peft_model(
    model,
    r=LORA_R,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    lora_alpha=16,
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing=True,
)

def formatting_prompts_func(examples):
    texts = []
    for convs in examples["conversations"]:
        parts = []
        for turn in convs:
            role = turn["from"]
            if role == "system":
                parts.append(f"### System:\n{turn['value']}")
            elif role == "human":
                parts.append(f"### User:\n{turn['value']}")
            else:
                parts.append(f"### Assistant:\n{turn['value']}")
        texts.append("\n".join(parts) + tokenizer.eos_token)
    return {"text": texts}

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",
    formatting_func=formatting_prompts_func,
    max_seq_length=MAX_SEQ_LENGTH,
    args=TrainingArguments(
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=10,
        max_steps=200,
        learning_rate=2e-4,
        fp16=not FastLanguageModel.is_bfloat16_supported(),
        bf16=FastLanguageModel.is_bfloat16_supported(),
        logging_steps=10,
        output_dir="outputs/llama31-support-lora",
    ),
)

trainer.train()
model.save_pretrained("outputs/llama31-support-lora")
tokenizer.save_pretrained("outputs/llama31-support-lora")
```

Ajuste `max_steps`, batch size e `LORA_R` conforme o tamanho do dataset e a VRAM disponível.

## 4. Exportar para GGUF

Unsloth facilita a conversão para quantização Ollama:

```python
from unsloth import FastLanguageModel

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="outputs/llama31-support-lora",
    max_seq_length=2048,
    load_in_4bit=True,
)

model.save_pretrained_gguf(
    "outputs/llama31-support-gguf",
    tokenizer,
    quantization_method="q4_k_m",
)
```

Isso gera arquivos `.gguf` na pasta `outputs/llama31-support-gguf`.

## 5. Carregar no Ollama

Crie um `Modelfile` na raiz do artefato GGUF:

```dockerfile
FROM ./Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf

PARAMETER temperature 0.7
PARAMETER num_ctx 4096

SYSTEM Você é um atendente profissional da empresa, empático e objetivo.
```

No host (ou dentro do container `ollama`):

```bash
ollama create customer-support -f Modelfile
ollama run customer-support "Olá, preciso de ajuda com meu pedido"
```

No Docker Compose deste projeto, o serviço `ollama` sobe por padrão com `make up` (ou `make setup` na primeira vez):

```bash
make up   # ou make setup na 1ª subida
docker exec -it autonomous-agent-ollama ollama create customer-support -f /path/Modelfile
```

Equivalente manual (sempre com `--env-file .env`):

```bash
docker compose --env-file .env -f infra/docker/docker-compose.yml up -d ollama
docker exec -it autonomous-agent-ollama ollama create customer-support -f /path/Modelfile
```

Configure no `.env`:

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=customer-support
```

## 6. Validar no agente

Reinicie `backend` e `worker` após alterar variáveis. O `ProviderFactory` usará `OllamaLLMProvider` para `identify_intent` e `generate_response`.

Teste rápido:

```bash
curl http://localhost:11434/api/chat -d '{
  "model": "customer-support",
  "messages": [{"role": "user", "content": "Quero cancelar"}],
  "stream": false
}'
```

## Referências

- [Unsloth — LoRA fine-tuning](https://github.com/unslothai/unsloth)
- [Ollama — Modelfile](https://github.com/ollama/ollama/blob/main/docs/modelfile.md)
- [Formato ShareGPT](./dataset_format.md)
