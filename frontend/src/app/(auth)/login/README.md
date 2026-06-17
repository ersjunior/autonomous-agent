# Login

Página de autenticação (`/login`). O usuário informa e-mail e senha; o frontend chama `POST /api/v1/auth/login`, recebe um **JWT** e o armazena para autenticar as chamadas seguintes.

- Componente: `src/components/LoginForm.tsx`.
- Credenciais de desenvolvimento (seed): `admin@admin.com` / `admin`.
- Em sucesso, redireciona para `/dashboard`.
