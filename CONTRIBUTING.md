# Contributing

Obrigado por contribuir com o **autonomous-agent**!

## Como começar

1. Faça fork do repositório
2. Crie uma branch: `git checkout -b feature/minha-feature`
3. Configure o ambiente local: `cp .env.example .env` e `make setup` (primeira vez) ou `make up`
4. Use sempre `make up` / `make setup` — o Makefile injeta `--env-file .env`; evite `docker compose -f infra/docker/docker-compose.yml up` sem o env-file da raiz
5. Implemente suas alterações com testes quando aplicável
6. Abra um Pull Request descrevendo o contexto e o plano de testes

## Padrões

- **Backend**: Python 3.12+, FastAPI, type hints
- **Frontend**: Next.js 15, TypeScript, Tailwind CSS
- **Workers**: Celery com Redis como broker
- **Commits**: mensagens claras no imperativo (ex.: `add auth endpoint`)

## Estrutura

Consulte o [README.md](README.md) para a visão geral da arquitetura e pastas do projeto.
