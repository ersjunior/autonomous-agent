# Auth

Grupo de rotas de autenticação (login e registro). É um **route group** (`(auth)`), então não adiciona prefixo à URL — as páginas ficam em `/login` e `/register`.

| Rota | Página |
|---|---|
| `/login` | Autenticação (e-mail + senha → JWT) |
| `/register` | Cadastro de novo usuário |

Usa `AuthShell` (`src/components/layout/AuthShell.tsx`) como casca visual. Após autenticar, o usuário é direcionado ao `/dashboard`.
