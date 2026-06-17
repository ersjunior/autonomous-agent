"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  cancelAppointment,
  createAppointment,
  fetchAppointments,
  fetchLeads,
  updateAppointment,
} from "@/lib/api-entities";
import {
  APPOINTMENT_SOURCE_LABELS,
  APPOINTMENT_STATUS_LABELS,
  appointmentStatusVariant,
  brLocalInputToUtcIso,
  defaultEndLocalFromStart,
  formatAppointmentDateTime,
  utcIsoToBrLocalInput,
} from "@/lib/appointment-datetime";
import type { Appointment, AppointmentStatus } from "@/lib/types/appointment";
import type { Lead } from "@/lib/types/leads";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { ConfirmDeleteModal } from "@/components/ui/ConfirmDeleteModal";
import { Modal } from "@/components/ui/Modal";
import { PageHeader } from "@/components/ui/PageHeader";

const STATUS_OPTIONS: AppointmentStatus[] = [
  "SCHEDULED",
  "CONFIRMED",
  "COMPLETED",
  "NO_SHOW",
  "CANCELLED",
];

const ACTIVE_STATUSES: AppointmentStatus[] = ["SCHEDULED", "CONFIRMED"];

export default function AppointmentsPage() {
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [filterStatus, setFilterStatus] = useState<AppointmentStatus | "">("");
  const [filterFrom, setFilterFrom] = useState("");
  const [filterTo, setFilterTo] = useState("");
  const [filterLeadId, setFilterLeadId] = useState("");

  const [createOpen, setCreateOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [leadId, setLeadId] = useState("");
  const [title, setTitle] = useState("Reunião");
  const [notes, setNotes] = useState("");
  const [startLocal, setStartLocal] = useState("");
  const [endLocal, setEndLocal] = useState("");

  const [cancelTarget, setCancelTarget] = useState<Appointment | null>(null);
  const [cancelling, setCancelling] = useState(false);

  const [rescheduleTarget, setRescheduleTarget] = useState<Appointment | null>(null);
  const [rescheduleStart, setRescheduleStart] = useState("");
  const [rescheduleEnd, setRescheduleEnd] = useState("");
  const [rescheduling, setRescheduling] = useState(false);

  const loadAppointments = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchAppointments({
        status: filterStatus || undefined,
        lead_id: filterLeadId || undefined,
        from: filterFrom || undefined,
        to: filterTo || undefined,
      });
      setAppointments(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar agendamentos.");
    } finally {
      setLoading(false);
    }
  }, [filterStatus, filterFrom, filterTo, filterLeadId]);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "/";
      return;
    }
    loadAppointments();
  }, [loadAppointments]);

  useEffect(() => {
    fetchLeads()
      .then(setLeads)
      .catch(() => setLeads([]));
  }, []);

  function openCreate() {
    setLeadId(leads[0]?.id ?? "");
    setTitle("Reunião");
    setNotes("");
    setStartLocal("");
    setEndLocal("");
    setCreateOpen(true);
    setError("");
    setSuccess("");
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!leadId || !startLocal || !endLocal) {
      setError("Preencha lead, início e fim.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await createAppointment({
        lead_id: leadId,
        title,
        notes: notes || null,
        starts_at: brLocalInputToUtcIso(startLocal),
        ends_at: brLocalInputToUtcIso(endLocal),
      });
      setSuccess("Agendamento criado com sucesso.");
      setCreateOpen(false);
      await loadAppointments();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao criar agendamento.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleStatusChange(appt: Appointment, status: AppointmentStatus) {
    setError("");
    try {
      await updateAppointment(appt.id, { status });
      setSuccess(`Status atualizado para ${APPOINTMENT_STATUS_LABELS[status]}.`);
      await loadAppointments();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao atualizar status.");
    }
  }

  async function confirmCancel() {
    if (!cancelTarget) {
      return;
    }
    setCancelling(true);
    setError("");
    try {
      await cancelAppointment(cancelTarget.id);
      setSuccess("Agendamento cancelado.");
      setCancelTarget(null);
      await loadAppointments();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao cancelar.");
    } finally {
      setCancelling(false);
    }
  }

  function openReschedule(appt: Appointment) {
    setRescheduleTarget(appt);
    setRescheduleStart(utcIsoToBrLocalInput(appt.starts_at));
    setRescheduleEnd(utcIsoToBrLocalInput(appt.ends_at));
    setError("");
  }

  async function confirmReschedule(e: FormEvent) {
    e.preventDefault();
    if (!rescheduleTarget || !rescheduleStart || !rescheduleEnd) {
      return;
    }
    setRescheduling(true);
    setError("");
    try {
      await updateAppointment(rescheduleTarget.id, {
        starts_at: brLocalInputToUtcIso(rescheduleStart),
        ends_at: brLocalInputToUtcIso(rescheduleEnd),
      });
      setSuccess("Agendamento remarcado.");
      setRescheduleTarget(null);
      await loadAppointments();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao remarcar.");
    } finally {
      setRescheduling(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Agendamentos"
        description="Visualize e gerencie compromissos criados pelo agente ou manualmente."
        actions={
          <button type="button" onClick={openCreate} className="btn-primary">
            Novo agendamento
          </button>
        }
      />

      {error && <Alert variant="error">{error}</Alert>}
      {success && <Alert variant="info">{success}</Alert>}

      <div className="glass-card mb-6 grid gap-4 p-5 md:grid-cols-4">
        <div>
          <label htmlFor="filterStatus" className="mb-1 block text-sm font-medium">
            Status
          </label>
          <select
            id="filterStatus"
            className="input-field w-full"
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value as AppointmentStatus | "")}
          >
            <option value="">Todos</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {APPOINTMENT_STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="filterFrom" className="mb-1 block text-sm font-medium">
            De (data)
          </label>
          <input
            id="filterFrom"
            type="date"
            className="input-field w-full"
            value={filterFrom}
            onChange={(e) => setFilterFrom(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="filterTo" className="mb-1 block text-sm font-medium">
            Até (data)
          </label>
          <input
            id="filterTo"
            type="date"
            className="input-field w-full"
            value={filterTo}
            onChange={(e) => setFilterTo(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="filterLead" className="mb-1 block text-sm font-medium">
            Lead
          </label>
          <select
            id="filterLead"
            className="input-field w-full"
            value={filterLeadId}
            onChange={(e) => setFilterLeadId(e.target.value)}
          >
            <option value="">Todos</option>
            {leads.map((lead) => (
              <option key={lead.id} value={lead.id}>
                {lead.nome_cliente}
              </option>
            ))}
          </select>
        </div>
      </div>

      {loading ? (
        <p className="text-muted-foreground">Carregando agendamentos...</p>
      ) : appointments.length === 0 ? (
        <p className="text-muted-foreground">Nenhum agendamento encontrado.</p>
      ) : (
        <div className="glass-card overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="px-4 py-3 font-medium">Data/hora</th>
                <th className="px-4 py-3 font-medium">Lead</th>
                <th className="px-4 py-3 font-medium">Título</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Canal</th>
                <th className="px-4 py-3 font-medium">Origem</th>
                <th className="px-4 py-3 font-medium">Ações</th>
              </tr>
            </thead>
            <tbody>
              {appointments.map((appt) => (
                <tr key={appt.id} className="border-b border-border/60 last:border-0">
                  <td className="px-4 py-3 whitespace-nowrap">
                    {formatAppointmentDateTime(appt.starts_at)}
                  </td>
                  <td className="px-4 py-3">{appt.lead_name ?? "—"}</td>
                  <td className="px-4 py-3">{appt.title}</td>
                  <td className="px-4 py-3">
                    <Badge variant={appointmentStatusVariant(appt.status)}>
                      {APPOINTMENT_STATUS_LABELS[appt.status] ?? appt.status}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 capitalize">{appt.channel ?? "—"}</td>
                  <td className="px-4 py-3">
                    {APPOINTMENT_SOURCE_LABELS[appt.created_by] ?? appt.created_by}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-2">
                      {ACTIVE_STATUSES.includes(appt.status) && (
                        <>
                          <button
                            type="button"
                            className="btn-secondary text-xs"
                            onClick={() => handleStatusChange(appt, "CONFIRMED")}
                          >
                            Confirmar
                          </button>
                          <button
                            type="button"
                            className="btn-secondary text-xs"
                            onClick={() => openReschedule(appt)}
                          >
                            Remarcar
                          </button>
                          <button
                            type="button"
                            className="btn-secondary text-xs text-destructive"
                            onClick={() => setCancelTarget(appt)}
                          >
                            Cancelar
                          </button>
                        </>
                      )}
                      {appt.status === "CONFIRMED" && (
                        <>
                          <button
                            type="button"
                            className="btn-secondary text-xs"
                            onClick={() => handleStatusChange(appt, "COMPLETED")}
                          >
                            Concluir
                          </button>
                          <button
                            type="button"
                            className="btn-secondary text-xs"
                            onClick={() => handleStatusChange(appt, "NO_SHOW")}
                          >
                            No-show
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Novo agendamento">
        <form onSubmit={handleCreate} className="space-y-4">
          <div>
            <label htmlFor="leadId" className="mb-1 block text-sm font-medium">
              Lead
            </label>
            <select
              id="leadId"
              required
              className="input-field w-full"
              value={leadId}
              onChange={(e) => setLeadId(e.target.value)}
            >
              <option value="" disabled>
                Selecione um lead
              </option>
              {leads.map((lead) => (
                <option key={lead.id} value={lead.id}>
                  {lead.nome_cliente}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="title" className="mb-1 block text-sm font-medium">
              Título
            </label>
            <input
              id="title"
              required
              className="input-field w-full"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label htmlFor="startLocal" className="mb-1 block text-sm font-medium">
                Início (horário de Brasília)
              </label>
              <input
                id="startLocal"
                type="datetime-local"
                required
                className="input-field w-full"
                value={startLocal}
                onChange={(e) => {
                  setStartLocal(e.target.value);
                  setEndLocal(defaultEndLocalFromStart(e.target.value));
                }}
              />
            </div>
            <div>
              <label htmlFor="endLocal" className="mb-1 block text-sm font-medium">
                Fim (horário de Brasília)
              </label>
              <input
                id="endLocal"
                type="datetime-local"
                required
                className="input-field w-full"
                value={endLocal}
                onChange={(e) => setEndLocal(e.target.value)}
              />
            </div>
          </div>
          <div>
            <label htmlFor="notes" className="mb-1 block text-sm font-medium">
              Notas
            </label>
            <textarea
              id="notes"
              className="input-field w-full min-h-[80px]"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
          <div className="flex justify-end gap-3">
            <button type="button" className="btn-secondary" onClick={() => setCreateOpen(false)}>
              Fechar
            </button>
            <button type="submit" className="btn-primary" disabled={submitting}>
              {submitting ? "Salvando..." : "Criar"}
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={rescheduleTarget !== null}
        onClose={() => setRescheduleTarget(null)}
        title="Remarcar agendamento"
      >
        {rescheduleTarget && (
          <form onSubmit={confirmReschedule} className="space-y-4">
            <p className="text-sm text-muted-foreground">
              {rescheduleTarget.title} — {rescheduleTarget.lead_name}
            </p>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="mb-1 block text-sm font-medium">Novo início</label>
                <input
                  type="datetime-local"
                  required
                  className="input-field w-full"
                  value={rescheduleStart}
                  onChange={(e) => {
                    setRescheduleStart(e.target.value);
                    setRescheduleEnd(defaultEndLocalFromStart(e.target.value));
                  }}
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium">Novo fim</label>
                <input
                  type="datetime-local"
                  required
                  className="input-field w-full"
                  value={rescheduleEnd}
                  onChange={(e) => setRescheduleEnd(e.target.value)}
                />
              </div>
            </div>
            <div className="flex justify-end gap-3">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setRescheduleTarget(null)}
              >
                Fechar
              </button>
              <button type="submit" className="btn-primary" disabled={rescheduling}>
                {rescheduling ? "Salvando..." : "Remarcar"}
              </button>
            </div>
          </form>
        )}
      </Modal>

      <ConfirmDeleteModal
        open={cancelTarget !== null}
        title="Cancelar agendamento"
        message={`Cancelar o agendamento "${cancelTarget?.title}" em ${cancelTarget ? formatAppointmentDateTime(cancelTarget.starts_at) : ""}?`}
        confirmLabel="Cancelar agendamento"
        loading={cancelling}
        onClose={() => setCancelTarget(null)}
        onConfirm={confirmCancel}
      />
    </>
  );
}
