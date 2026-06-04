export interface RecordActions {
  canView: boolean;
  canEdit: boolean;
  canDelete: boolean;
}

export interface OwnableRecord {
  is_system?: boolean;
}

export function actionsFor(record: OwnableRecord): RecordActions {
  if (record.is_system) {
    return { canView: true, canEdit: false, canDelete: false };
  }
  return { canView: true, canEdit: true, canDelete: true };
}

export type LeadBaseSource = "IMPORT" | "MANUAL";

export function isImportLeadBase(source?: LeadBaseSource): boolean {
  return source === "IMPORT";
}

export function leadActionsFor(
  base: { source?: LeadBaseSource; is_system?: boolean } | null,
  lead?: OwnableRecord,
): RecordActions {
  if (base?.is_system || lead?.is_system) {
    return { canView: true, canEdit: false, canDelete: false };
  }
  if (isImportLeadBase(base?.source)) {
    return { canView: true, canEdit: false, canDelete: false };
  }
  return { canView: true, canEdit: true, canDelete: true };
}

export function canDeleteLeadBase(base: { is_system?: boolean } | null): boolean {
  return Boolean(base && !base.is_system);
}
