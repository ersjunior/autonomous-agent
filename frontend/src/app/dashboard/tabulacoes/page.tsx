"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  createTabulacao,
  deleteTabulacao,
  fetchTabulacoes,
  updateTabulacao,
} from "@/lib/api-entities";
import { actionsFor } from "@/lib/protection";
import type { Tabulacao, TabulacaoCategoria } from "@/lib/types/tabulacoes";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { ConfirmDeleteModal } from "@/components/ui/ConfirmDeleteModal";
import { Modal } from "@/components/ui/Modal";
import { PageHeader } from "@/components/ui/PageHeader";
import { RecordActionsBar } from "@/components/ui/RecordActions";
import { SystemBadge } from "@/components/ui/SystemBadge";

const CATEGORIAS: TabulacaoCategoria[] = ["TELEFONIA", "NEGOCIO", "CUSTOMIZADO"];

const CATEGORIA_LABELS: Record<TabulacaoCategoria, string> = {
  TELEFONIA: "Telefonia",
  NEGOCIO: "Negócio",
  CUSTOMIZADO: "Customizado",
};

type FormMode = "create" | "edit" | "view" | null;

export default function TabulacoesPage() {
  const [tabulacoes, setTabulacoes] = useState<Tabulacao[]>([]);
  const [loading, setLoading] = useState(true);
  const [formMode, setFormMode] = useState<FormMode>(null);
  const [selected, setSelected] = useState<Tabulacao | null>(null);
  const [nome, setNome] = useState("");
  const [codigo, setCodigo] = useState("");
  const [categoria, setCategoria] = useState<TabulacaoCategoria>("CUSTOMIZADO");
  const [isTerminal, setIsTerminal] = useState(false);
  const [descricao, setDescricao] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Tabulacao | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function loadTabulacoes() {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }

    try {
      setTabulacoes(await fetchTabulacoes());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar tabulações.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadTabulacoes();
  }, []);

  function openCreate() {
    setSelected(null);
    setNome("");
    setCodigo("");
    setCategoria("CUSTOMIZADO");
    setIsTerminal(false);
    setDescricao("");
    setFormMode("create");
    setError("");
    setSuccess("");
  }

  function openView(item: Tabulacao) {
    setSelected(item);
    setNome(item.nome);
    setCodigo(item.codigo);
    setCategoria(item.categoria);
    setIsTerminal(item.is_terminal);
    setDescricao(item.descricao ?? "");
    setFormMode("view");
    setError("");
  }

  function openEdit(item: Tabulacao) {
    setSelected(item);
    setNome(item.nome);
    setCodigo(item.codigo);
    setCategoria(item.categoria);
    setIsTerminal(item.is_terminal);
    setDescricao(item.descricao ?? "");
    setFormMode("edit");
    setError("");
    setSuccess("");
  }

  function closeForm() {
    setFormMode(null);
    setSelected(null);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSuccess("");
    setSubmitting(true);

    try {
      if (formMode === "create") {
        await createTabulacao({
          nome,
          codigo,
          categoria,
          is_terminal: isTerminal,
          descricao: descricao || null,
        });
        setSuccess("Tabulação criada com sucesso.");
      } else if (formMode === "edit" && selected) {
        await updateTabulacao(selected.id, {
          nome,
          codigo,
          categoria,
          is_terminal: isTerminal,
          descricao: descricao || null,
        });
        setSuccess("Tabulação atualizada com sucesso.");
      }
      closeForm();
      await loadTabulacoes();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar tabulação.");
    } finally {
      setSubmitting(false);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) {
      return;
    }
    setDeleting(true);
    setError("");
    try {
      await deleteTabulacao(deleteTarget.id);
      setSuccess("Tabulação excluída.");
      setDeleteTarget(null);
      await loadTabulacoes();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao excluir tabulação.");
    } finally {
      setDeleting(false);
    }
  }

  const readOnly = formMode === "view";
  const showInlineForm = formMode === "create";

  return (
    <>
      <PageHeader
        title="Tabulações"
        description="Classifique resultados de atendimento por telefonia, negócio ou regras customizadas."
        actions={
          <button type="button" onClick={openCreate} className="btn-primary">
            {showInlineForm ? "Cancelar" : "Nova tabulação"}
          </button>
        }
      />

      {error && <Alert variant="error">{error}</Alert>}
      {success && <Alert variant="info">{success}</Alert>}

      {showInlineForm && (
        <div className="glass-card mb-8 p-6">
          <h2 className="mb-5 text-lg font-semibold text-foreground">Nova tabulação</h2>
          <TabulacaoFormFields
            nome={nome}
            codigo={codigo}
            categoria={categoria}
            isTerminal={isTerminal}
            descricao={descricao}
            readOnly={false}
            onNomeChange={setNome}
            onCodigoChange={setCodigo}
            onCategoriaChange={setCategoria}
            onIsTerminalChange={setIsTerminal}
            onDescricaoChange={setDescricao}
            onSubmit={handleSubmit}
            submitting={submitting}
            submitLabel="Salvar tabulação"
          />
        </div>
      )}

      {loading ? (
        <p className="text-muted-foreground">Carregando tabulações...</p>
      ) : tabulacoes.length === 0 ? (
        <div className="glass-card p-8 text-center text-muted-foreground">
          Nenhuma tabulação cadastrada.
        </div>
      ) : (
        <div className="glass-card overflow-hidden">
          <table className="min-w-full divide-y divide-border">
            <thead className="bg-muted/50">
              <tr>
                {["Nome", "Código", "Categoria", "Terminal", "Ações"].map((col) => (
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
              {tabulacoes.map((item) => {
                const actions = actionsFor(item);
                return (
                  <tr key={item.id} className="transition hover:bg-muted/30">
                    <td className="px-6 py-4 text-sm">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-medium text-foreground">{item.nome}</p>
                        {item.is_system && <SystemBadge />}
                      </div>
                      {item.descricao && (
                        <p className="mt-1 line-clamp-2 text-muted-foreground">
                          {item.descricao}
                        </p>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 font-mono text-sm text-foreground">
                      {item.codigo}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm">
                      <Badge>{CATEGORIA_LABELS[item.categoria]}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-foreground">
                      {item.is_terminal ? "Sim" : "Não"}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm">
                      <RecordActionsBar
                        actions={actions}
                        onView={() => openView(item)}
                        onEdit={() => openEdit(item)}
                        onDelete={() => setDeleteTarget(item)}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={formMode === "view" || formMode === "edit"}
        title={
          formMode === "view"
            ? "Visualizar tabulação"
            : formMode === "edit"
              ? "Editar tabulação"
              : ""
        }
        onClose={closeForm}
        wide={formMode === "view"}
      >
        <TabulacaoFormFields
          nome={nome}
          codigo={codigo}
          categoria={categoria}
          isTerminal={isTerminal}
          descricao={descricao}
          readOnly={readOnly}
          onNomeChange={setNome}
          onCodigoChange={setCodigo}
          onCategoriaChange={setCategoria}
          onIsTerminalChange={setIsTerminal}
          onDescricaoChange={setDescricao}
          onSubmit={handleSubmit}
          submitting={submitting}
          submitLabel="Salvar alterações"
          hideSubmit={readOnly}
        />
      </Modal>

      <ConfirmDeleteModal
        open={deleteTarget !== null}
        title="Excluir tabulação"
        message={`Tem certeza que deseja excluir a tabulação "${deleteTarget?.nome}"? Esta ação não pode ser desfeita.`}
        loading={deleting}
        onClose={() => setDeleteTarget(null)}
        onConfirm={confirmDelete}
      />
    </>
  );
}

function TabulacaoFormFields({
  nome,
  codigo,
  categoria,
  isTerminal,
  descricao,
  readOnly,
  onNomeChange,
  onCodigoChange,
  onCategoriaChange,
  onIsTerminalChange,
  onDescricaoChange,
  onSubmit,
  submitting,
  submitLabel,
  hideSubmit = false,
}: {
  nome: string;
  codigo: string;
  categoria: TabulacaoCategoria;
  isTerminal: boolean;
  descricao: string;
  readOnly: boolean;
  onNomeChange: (v: string) => void;
  onCodigoChange: (v: string) => void;
  onCategoriaChange: (v: TabulacaoCategoria) => void;
  onIsTerminalChange: (v: boolean) => void;
  onDescricaoChange: (v: string) => void;
  onSubmit: (e: FormEvent) => void;
  submitting: boolean;
  submitLabel: string;
  hideSubmit?: boolean;
}) {
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div>
        <label htmlFor="tabNome" className="mb-2 block text-sm font-medium text-foreground">
          Nome
        </label>
        <input
          id="tabNome"
          type="text"
          required
          disabled={readOnly}
          value={nome}
          onChange={(e) => onNomeChange(e.target.value)}
          className="input-field disabled:opacity-70"
        />
      </div>

      <div>
        <label htmlFor="tabCodigo" className="mb-2 block text-sm font-medium text-foreground">
          Código
        </label>
        <input
          id="tabCodigo"
          type="text"
          required
          disabled={readOnly}
          value={codigo}
          onChange={(e) => onCodigoChange(e.target.value)}
          placeholder="Ex: CUSTOM:MINHA_REGRA"
          className="input-field font-mono disabled:opacity-70"
        />
      </div>

      <div>
        <label htmlFor="tabCategoria" className="mb-2 block text-sm font-medium text-foreground">
          Categoria
        </label>
        <select
          id="tabCategoria"
          disabled={readOnly}
          value={categoria}
          onChange={(e) => onCategoriaChange(e.target.value as TabulacaoCategoria)}
          className="input-field disabled:opacity-70"
        >
          {CATEGORIAS.map((c) => (
            <option key={c} value={c}>
              {CATEGORIA_LABELS[c]}
            </option>
          ))}
        </select>
      </div>

      <div className="flex items-center gap-3">
        <input
          id="tabTerminal"
          type="checkbox"
          disabled={readOnly}
          checked={isTerminal}
          onChange={(e) => onIsTerminalChange(e.target.checked)}
          className="h-4 w-4 rounded border-border"
        />
        <label htmlFor="tabTerminal" className="text-sm font-medium text-foreground">
          Tabulação terminal (encerra o fluxo de atendimento)
        </label>
      </div>

      <div>
        <label htmlFor="tabDescricao" className="mb-2 block text-sm font-medium text-foreground">
          Descrição
        </label>
        <textarea
          id="tabDescricao"
          rows={readOnly ? 4 : 3}
          disabled={readOnly}
          value={descricao}
          onChange={(e) => onDescricaoChange(e.target.value)}
          className="input-field resize-none disabled:opacity-70"
        />
      </div>

      {!hideSubmit && (
        <button type="submit" disabled={submitting} className="btn-primary">
          {submitting ? "Salvando..." : submitLabel}
        </button>
      )}
    </form>
  );
}
