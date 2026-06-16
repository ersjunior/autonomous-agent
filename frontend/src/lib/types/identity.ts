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
