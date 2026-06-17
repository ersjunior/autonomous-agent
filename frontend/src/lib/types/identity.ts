export interface InstitutionalIdentity {
  company_name: string | null;
  display_name: string | null;
  tone: string | null;
  business_context: string | null;
  greeting_hint: string | null;
}

export type InstitutionalIdentityUpdate = Partial<InstitutionalIdentity>;

export const EMPTY_INSTITUTIONAL_IDENTITY: InstitutionalIdentity = {
  company_name: null,
  display_name: null,
  tone: null,
  business_context: null,
  greeting_hint: null,
};

export function identityToFormValues(
  data: InstitutionalIdentity | null | undefined
): Record<keyof InstitutionalIdentity, string> {
  return {
    company_name: data?.company_name ?? "",
    display_name: data?.display_name ?? "",
    tone: data?.tone ?? "",
    business_context: data?.business_context ?? "",
    greeting_hint: data?.greeting_hint ?? "",
  };
}

export function formValuesToIdentityUpdate(
  values: Record<keyof InstitutionalIdentity, string>
): InstitutionalIdentityUpdate {
  const normalize = (value: string): string | null => {
    const trimmed = value.trim();
    return trimmed || null;
  };

  return {
    company_name: normalize(values.company_name),
    display_name: normalize(values.display_name),
    tone: normalize(values.tone),
    business_context: normalize(values.business_context),
    greeting_hint: normalize(values.greeting_hint),
  };
}

export function identityFromAgentConfig(
  config: Record<string, unknown> | null | undefined
): InstitutionalIdentity {
  const raw = config?.identity;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { ...EMPTY_INSTITUTIONAL_IDENTITY };
  }
  const identity = raw as Record<string, unknown>;
  const field = (key: keyof InstitutionalIdentity): string | null => {
    const value = identity[key];
    if (value == null) return null;
    const text = String(value).trim();
    return text || null;
  };
  return {
    company_name: field("company_name"),
    display_name: field("display_name"),
    tone: field("tone"),
    business_context: field("business_context"),
    greeting_hint: field("greeting_hint"),
  };
}

export function configWithoutIdentity(
  config: Record<string, unknown> | null | undefined
): Record<string, unknown> {
  if (!config) return {};
  const { identity: _identity, ...rest } = config;
  return rest;
}
