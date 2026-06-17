# Register

Página de cadastro de usuários (`/register`). Cria uma nova conta via `POST /api/v1/auth/register` e, em seguida, permite autenticar em `/login`.

Cada usuário é dono dos seus recursos (agentes, leads, documentos da KB) — a separação por dono (`owner_user_id`) é aplicada no backend (`app/core/authorization.py`).
