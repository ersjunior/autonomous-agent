"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { AuthFooterLink, AuthShell } from "@/components/layout/AuthShell";
import { Alert } from "@/components/ui/Alert";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function resolveEmail(username: string): string {
  return username.includes("@") ? username : `${username}@admin.com`;
}

export default function LoginForm() {
  const router = useRouter();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await fetch(`${API_URL}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: resolveEmail(username.trim()),
          password,
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.detail || "Usuário ou senha incorretos.");
        return;
      }

      const data = await res.json();
      localStorage.setItem("access_token", data.access_token);
      router.push("/dashboard");
    } catch {
      setError("Erro de conexão. Tente novamente.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell
      title="Autonomous Agent"
      subtitle="Entre para gerenciar seus agentes de IA."
      footer={
        <AuthFooterLink text="Não tem conta?" linkText="Cadastre-se" href="/register" />
      }
    >
      {error && <Alert>{error}</Alert>}

      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label htmlFor="username" className="mb-2 block text-sm font-medium text-foreground">
            Usuário
          </label>
          <input
            id="username"
            type="text"
            required
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="input-field"
            placeholder="admin"
          />
        </div>

        <div>
          <label htmlFor="password" className="mb-2 block text-sm font-medium text-foreground">
            Senha
          </label>
          <input
            id="password"
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="input-field"
            placeholder="••••••••"
          />
        </div>

        <button type="submit" disabled={loading} className="btn-primary w-full">
          {loading ? "Entrando..." : "Entrar"}
        </button>
      </form>
    </AuthShell>
  );
}
