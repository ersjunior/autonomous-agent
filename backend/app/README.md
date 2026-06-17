# App

Pacote principal da aplicação **FastAPI**. Concentra a API REST, os WebSockets de monitoramento, os webhooks de canais e a inicialização do serviço. A lógica de IA fica em `agents/` (raiz), importada via `PYTHONPATH`.

## Estrutura

```
app/
├── main.py       # instância FastAPI, CORS, lifespan (migrations + seed + bootstrap)
├── api/v1/        # routers REST + WebSocket de monitoramento
├── core/          # config, database, security, authorization, seed, erlang, túnel…
├── models/        # modelos SQLAlchemy (schema do banco)
├── schemas/       # schemas Pydantic v2 (validação de entrada/saída)
└── services/      # regras de negócio (KB, handoff, capacidade, voz, identidade…)
```

## Startup (lifespan)

No arranque, `main.py`:

1. Cria a extensão PostgreSQL `vector` (pgvector).
2. Executa `alembic upgrade head` (o schema vem das migrations — fonte única).
3. Faz seed do admin de desenvolvimento e bootstrap das configurações dinâmicas.

## Camadas

- **api/** expõe rotas e delega para **services/**.
- **services/** concentra a regra de negócio e usa **models/**.
- **schemas/** valida e serializa os contratos da API (não confundir com **models/**, que é o ORM).
