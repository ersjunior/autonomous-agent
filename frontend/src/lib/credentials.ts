export const SECRET_MASK = "********";

const CHANNEL_SECRET_KEYS = new Set([
  "auth_token",
  "bot_token",
  "account_sid",
]);

export function isSecretCredentialKey(key: string): boolean {
  return CHANNEL_SECRET_KEYS.has(key);
}

export function isMaskedSecretValue(value: string): boolean {
  if (!value.trim()) {
    return true;
  }
  if (value === SECRET_MASK) {
    return true;
  }
  return value.includes("...");
}

export function maskCredentialValue(key: string, value: unknown): unknown {
  if (value === null || value === undefined || value === "") {
    return value;
  }
  if (isSecretCredentialKey(key)) {
    return SECRET_MASK;
  }
  return value;
}

export function maskCredentials(credentials: Record<string, unknown>): Record<string, unknown> {
  const masked: Record<string, unknown> = { ...credentials };
  for (const key of Object.keys(masked)) {
    masked[key] = maskCredentialValue(key, masked[key]);
  }
  return masked;
}

/** Merge edited flat fields into credentials; skip masked secrets (keep original). */
export function mergeChannelCredentials(
  original: Record<string, unknown>,
  edited: Record<string, string>,
  channelType: string,
): Record<string, unknown> {
  if (channelType === "VOICE") {
    const phoneNumbers = edited.phone_numbers
      ? edited.phone_numbers
          .split(",")
          .map((n) => n.trim())
          .filter(Boolean)
      : (original.phone_numbers as string[]) ?? [];
    return {
      provider: edited.provider || original.provider || "twilio",
      phone_numbers: phoneNumbers,
    };
  }

  const merged: Record<string, unknown> = { ...original };
  for (const [key, value] of Object.entries(edited)) {
    if (isSecretCredentialKey(key) && isMaskedSecretValue(value)) {
      continue;
    }
    merged[key] = value;
  }
  return merged;
}

export function credentialsToFormValues(
  credentials: Record<string, unknown>,
  channelType: string,
  maskSecrets: boolean,
): Record<string, string> {
  const creds = maskSecrets ? maskCredentials(credentials) : credentials;
  if (channelType === "VOICE") {
    const phones = Array.isArray(creds.phone_numbers)
      ? (creds.phone_numbers as string[]).join(", ")
      : "";
    return {
      phone_numbers: phones,
      provider: String(creds.provider ?? "twilio"),
    };
  }
  const flat: Record<string, string> = {};
  for (const [key, value] of Object.entries(creds)) {
    flat[key] = value === null || value === undefined ? "" : String(value);
  }
  return flat;
}
