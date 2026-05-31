# Formato do dataset para fine-tuning LLM

Use o formato **ShareGPT** (conversas multi-turn) para adaptar o modelo ao domínio de atendimento.

## Estrutura JSON

Cada exemplo é um objeto com a chave `conversations`:

```json
{
  "conversations": [
    { "from": "system", "value": "Você é um atendente da empresa X..." },
    { "from": "human", "value": "Quero cancelar meu plano." },
    { "from": "gpt", "value": "Entendo. Posso confirmar seu CPF para localizar o contrato?" },
    { "from": "human", "value": "123.456.789-00" },
    { "from": "gpt", "value": "Encontrei seu plano Premium. Deseja cancelar ao final do ciclo ou imediatamente?" }
  ]
}
```

## Papéis (`from`)

| Valor | Significado |
|-------|-------------|
| `system` | Instrução de persona e políticas |
| `human` | Mensagem do cliente |
| `gpt` | Resposta ideal do atendente |

## Boas práticas

- Inclua casos de **escalação** (`escalate`) com respostas que encaminham ao humano.
- Cubra intenções do classificador: `greeting`, `question`, `complaint`, `purchase`, `cancel`.
- Evite respostas genéricas; use nomes de produtos, políticas e tom da marca.
- Mantenha 3–8 turnos por exemplo; datasets muito curtos overfitam.
- Separe 90% treino / 10% validação antes do treino LoRA.

## Arquivo de exemplo

Salve como `data/customer_support_sharegpt.json`:

```json
[
  {
    "conversations": [
      { "from": "system", "value": "Você atende clientes da Operadora Demo com tom empático." },
      { "from": "human", "value": "Minha internet caiu de novo." },
      { "from": "gpt", "value": "Sinto muito pelo transtorno. Vou verificar a região do seu CEP. Pode informar o CEP?" }
    ]
  }
]
```
