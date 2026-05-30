"use client";

import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";

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
      window.location.href = "/login";
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
    <main className="p-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Leads</h1>
          <p className="mt-1 text-gray-600">Gerencie sua base de contatos.</p>
        </div>
        <div className="flex gap-3">
          <label className="cursor-pointer rounded-md border border-gray-300 bg-white px-4 py-2 font-medium text-gray-700 hover:bg-gray-50">
            Importar CSV
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              onChange={handleCsvUpload}
              className="hidden"
            />
          </label>
          <button
            onClick={() => setShowForm(!showForm)}
            className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700"
          >
            {showForm ? "Cancelar" : "Novo Lead"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {uploadProgress && (
        <div className="mb-4 rounded-lg bg-white p-4 shadow">
          <div className="mb-2 flex justify-between text-sm text-gray-600">
            <span>
              Importando {uploadProgress.current} de {uploadProgress.total}
            </span>
            {uploadProgress.errors > 0 && (
              <span className="text-red-600">{uploadProgress.errors} erro(s)</span>
            )}
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-gray-200">
            <div
              className="h-full bg-blue-600 transition-all"
              style={{
                width: `${(uploadProgress.current / uploadProgress.total) * 100}%`,
              }}
            />
          </div>
        </div>
      )}

      {showForm && (
        <div className="mb-8 rounded-lg bg-white p-6 shadow">
          <h2 className="mb-4 text-lg font-semibold text-gray-900">Novo lead</h2>
          <form onSubmit={handleManualSubmit} className="space-y-4">
            <div>
              <label htmlFor="name" className="mb-1 block text-sm font-medium text-gray-700">
                Nome
              </label>
              <input
                id="name"
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div>
              <label htmlFor="phone" className="mb-1 block text-sm font-medium text-gray-700">
                Telefone
              </label>
              <input
                id="phone"
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div>
              <label htmlFor="email" className="mb-1 block text-sm font-medium text-gray-700">
                Email
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <button
              type="submit"
              disabled={submitting}
              className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {submitting ? "Salvando..." : "Salvar lead"}
            </button>
          </form>
        </div>
      )}

      {loading ? (
        <p className="text-gray-500">Carregando leads...</p>
      ) : leads.length === 0 ? (
        <p className="text-gray-500">Nenhum lead cadastrado.</p>
      ) : (
        <div className="overflow-hidden rounded-lg bg-white shadow">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Nome
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Telefone
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Email
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Status
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {leads.map((lead) => (
                <tr key={lead.id}>
                  <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-gray-900">
                    {lead.name}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                    {lead.phone || "—"}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                    {lead.email || "—"}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm">
                    <span className="inline-flex rounded-full bg-blue-100 px-2 py-1 text-xs font-semibold text-blue-800">
                      {lead.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
