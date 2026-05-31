"use client";

import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { PageHeader } from "@/components/ui/PageHeader";

interface Lead {
  id: string;
  name: string;
  phone?: string;
  email?: string;
  status: string;
  created_at: string;
}

interface UploadProgress {
  total: number;
  current: number;
  errors: number;
}

function parseCsv(content: string): Array<{ name: string; phone: string; email: string }> {
  const lines = content.trim().split(/\r?\n/);
  if (lines.length === 0) return [];

  const header = lines[0].split(",").map((h) => h.trim().toLowerCase());
  const nameIdx = header.indexOf("name");
  const phoneIdx = header.indexOf("phone");
  const emailIdx = header.indexOf("email");

  const rows: Array<{ name: string; phone: string; email: string }> = [];

  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(",").map((c) => c.trim());
    if (cols.length === 0 || cols.every((c) => !c)) continue;

    rows.push({
      name: nameIdx >= 0 ? cols[nameIdx] || "" : cols[0] || "",
      phone: phoneIdx >= 0 ? cols[phoneIdx] || "" : cols[1] || "",
      email: emailIdx >= 0 ? cols[emailIdx] || "" : cols[2] || "",
    });
  }

  return rows.filter((r) => r.name);
}

export default function LeadsPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function loadLeads() {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }

    try {
      const res = await apiFetch("/api/v1/leads/");
      if (res.ok) {
        setLeads(await res.json());
      }
    } catch {
      setError("Erro ao carregar leads.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadLeads();
  }, []);

  async function createLead(data: { name: string; phone: string; email: string }) {
    const res = await apiFetch("/api/v1/leads/", {
      method: "POST",
      body: JSON.stringify({
        name: data.name,
        phone: data.phone || null,
        email: data.email || null,
      }),
    });
    return res.ok;
  }

  async function handleManualSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      const ok = await createLead({ name, phone, email });
      if (!ok) {
        setError("Erro ao criar lead.");
        return;
      }

      setShowForm(false);
      setName("");
      setPhone("");
      setEmail("");
      await loadLeads();
    } catch {
      setError("Erro de conexão. Tente novamente.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCsvUpload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    setError("");
    const content = await file.text();
    const rows = parseCsv(content);

    if (rows.length === 0) {
      setError("CSV vazio ou sem dados válidos. Use colunas: name, phone, email.");
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }

    setUploadProgress({ total: rows.length, current: 0, errors: 0 });

    let errors = 0;
    for (let i = 0; i < rows.length; i++) {
      const ok = await createLead(rows[i]);
      if (!ok) errors++;
      setUploadProgress({ total: rows.length, current: i + 1, errors });
    }

    setUploadProgress(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
    await loadLeads();

    if (errors > 0) {
      setError(`${errors} lead(s) falharam no upload.`);
    }
  }

  return (
    <>
      <PageHeader
        title="Leads"
        description="Gerencie sua base de contatos e importações."
        actions={
          <>
            <label className="btn-secondary cursor-pointer">
              Importar CSV
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv"
                onChange={handleCsvUpload}
                className="hidden"
              />
            </label>
            <button type="button" onClick={() => setShowForm(!showForm)} className="btn-primary">
              {showForm ? "Cancelar" : "Novo lead"}
            </button>
          </>
        }
      />

      {error && <Alert>{error}</Alert>}

      {uploadProgress && (
        <div className="glass-card mb-6 p-5">
          <div className="mb-2 flex justify-between text-sm text-muted-foreground">
            <span>
              Importando {uploadProgress.current} de {uploadProgress.total}
            </span>
            {uploadProgress.errors > 0 && (
              <span className="text-destructive">{uploadProgress.errors} erro(s)</span>
            )}
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{
                width: `${(uploadProgress.current / uploadProgress.total) * 100}%`,
              }}
            />
          </div>
        </div>
      )}

      {showForm && (
        <div className="glass-card mb-8 p-6">
          <h2 className="mb-5 text-lg font-semibold text-foreground">Novo lead</h2>
          <form onSubmit={handleManualSubmit} className="space-y-4">
            {[
              { id: "name", label: "Nome", type: "text", required: true, value: name, set: setName },
              { id: "phone", label: "Telefone", type: "tel", required: false, value: phone, set: setPhone },
              { id: "email", label: "Email", type: "email", required: false, value: email, set: setEmail },
            ].map((field) => (
              <div key={field.id}>
                <label htmlFor={field.id} className="mb-2 block text-sm font-medium text-foreground">
                  {field.label}
                </label>
                <input
                  id={field.id}
                  type={field.type}
                  required={field.required}
                  value={field.value}
                  onChange={(e) => field.set(e.target.value)}
                  className="input-field"
                />
              </div>
            ))}
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? "Salvando..." : "Salvar lead"}
            </button>
          </form>
        </div>
      )}

      {loading ? (
        <p className="text-muted-foreground">Carregando leads...</p>
      ) : leads.length === 0 ? (
        <div className="glass-card p-8 text-center text-muted-foreground">
          Nenhum lead cadastrado.
        </div>
      ) : (
        <div className="glass-card overflow-hidden">
          <table className="min-w-full divide-y divide-border">
            <thead className="bg-muted/50">
              <tr>
                {["Nome", "Telefone", "Email", "Status"].map((col) => (
                  <th
                    key={col}
                    className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {leads.map((lead) => (
                <tr key={lead.id} className="transition hover:bg-muted/30">
                  <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-foreground">
                    {lead.name}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-muted-foreground">
                    {lead.phone || "—"}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-muted-foreground">
                    {lead.email || "—"}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm">
                    <Badge>{lead.status}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
