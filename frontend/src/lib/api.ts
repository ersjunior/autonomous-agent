import type {
  AvatarImageInfo,
  AvatarImageUploadResponse,
  AvatarTestResponse,
  SettingsResponse,
  VoiceSampleInfo,
  VoiceSampleUploadResponse,
  VoiceTestResponse,
} from "@/lib/types/settings";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const AUTH_API_PATHS = ["/api/v1/auth/login", "/api/v1/auth/register"];

function resolveRequestPath(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) {
    try {
      return new URL(path).pathname;
    } catch {
      return path;
    }
  }
  return path.split("?")[0];
}

function isAuthApiPath(path: string): boolean {
  const normalized = resolveRequestPath(path);
  return AUTH_API_PATHS.includes(normalized);
}

function isOnAuthPage(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  const pathname = window.location.pathname;
  return pathname === "/" || pathname === "/register";
}

/** Clears session and redirects to login. Returns true if the response was 401. */
export function handleUnauthorized(response: Response, requestPath: string): boolean {
  if (response.status !== 401) {
    return false;
  }
  if (isAuthApiPath(requestPath)) {
    return true;
  }
  if (typeof window === "undefined") {
    return true;
  }

  localStorage.removeItem("access_token");

  if (!isOnAuthPage()) {
    window.location.href = "/";
  }

  return true;
}

export async function formatApiError(res: Response, context: string): Promise<string> {
  if (res.status === 401) {
    return "Sessão expirada. Faça login novamente.";
  }

  const data = await res.json().catch(() => null);
  const detail = data?.detail;

  let detailText = "";
  if (typeof detail === "string") {
    detailText = detail;
  } else if (Array.isArray(detail)) {
    detailText = detail
      .map((item: { msg?: string }) => item?.msg)
      .filter(Boolean)
      .join(", ");
  }

  if (detailText) {
    return `${context} (HTTP ${res.status}): ${detailText}`;
  }
  return `${context} (HTTP ${res.status})`;
}

function authHeaders(options: RequestInit = {}): Headers {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("access_token") : null;

  const headers = new Headers(options.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

function downloadHeaders(): Headers {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("access_token") : null;

  const headers = new Headers();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

async function checkedFetch(
  url: string,
  init: RequestInit,
  requestPath: string
): Promise<Response> {
  const res = await fetch(url, init);
  handleUnauthorized(res, requestPath);
  return res;
}

export async function apiFetch(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  return checkedFetch(`${API_URL}${path}`, { ...options, headers: authHeaders(options) }, path);
}

export async function apiUpload(
  path: string,
  formData: FormData
): Promise<Response> {
  return checkedFetch(
    `${API_URL}${path}`,
    {
      method: "POST",
      headers: downloadHeaders(),
      body: formData,
    },
    path
  );
}

export { API_URL };

export async function apiDownload(path: string, fallbackFilename = "download"): Promise<void> {
  const res = await checkedFetch(`${API_URL}${path}`, { headers: downloadHeaders() }, path);
  if (!res.ok) {
    throw new Error(await formatApiError(res, "Falha no download"));
  }

  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition");
  let filename = fallbackFilename;
  const match = disposition?.match(/filename="([^"]+)"/);
  if (match?.[1]) {
    filename = match[1];
  }

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export async function getCampaignMetrics(campaignId: string): Promise<Response> {
  return apiFetch(`/api/v1/campaigns/${campaignId}/metrics`);
}

export async function getLeadBaseMetrics(leadBaseId: string): Promise<Response> {
  return apiFetch(`/api/v1/lead-bases/${leadBaseId}/metrics`);
}

export async function getSettings(): Promise<Response> {
  return apiFetch("/api/v1/settings");
}

export async function updateSettings(
  changes: Record<string, string | null>
): Promise<Response> {
  return apiFetch("/api/v1/settings", {
    method: "PUT",
    body: JSON.stringify({ settings: changes }),
  });
}

export async function uploadVoiceSample(file: File): Promise<Response> {
  const formData = new FormData();
  formData.append("file", file);
  return apiUpload("/api/v1/settings/voice-sample", formData);
}

export async function getVoiceSampleInfo(): Promise<Response> {
  return apiFetch("/api/v1/settings/voice-sample/info");
}

const VOICE_SAMPLE_AUDIO_PATH = "/api/v1/settings/voice-sample/audio";

export async function fetchVoiceSampleAudio(): Promise<Blob> {
  return fetchAudioBlob(VOICE_SAMPLE_AUDIO_PATH);
}

export async function testVoice(text?: string): Promise<Response> {
  return apiFetch("/api/v1/settings/voice-test", {
    method: "POST",
    body: JSON.stringify({ text: text ?? null }),
  });
}

export async function fetchAudioBlob(path: string): Promise<Blob> {
  const res = await checkedFetch(`${API_URL}${path}`, { headers: downloadHeaders() }, path);
  if (!res.ok) {
    throw new Error(await formatApiError(res, "Falha ao carregar áudio"));
  }
  return res.blob();
}

export async function getAvatarImageInfo(): Promise<Response> {
  return apiFetch("/api/v1/settings/avatar-image/info");
}

const AVATAR_IMAGE_PREVIEW_PATH = "/api/v1/settings/avatar-image/preview";

export async function fetchAvatarImage(): Promise<Blob> {
  const res = await checkedFetch(
    `${API_URL}${AVATAR_IMAGE_PREVIEW_PATH}`,
    { headers: downloadHeaders() },
    AVATAR_IMAGE_PREVIEW_PATH
  );
  if (!res.ok) {
    throw new Error(await formatApiError(res, "Falha ao carregar imagem do avatar"));
  }
  return res.blob();
}

export async function uploadAvatarImage(file: File): Promise<Response> {
  const formData = new FormData();
  formData.append("file", file);
  return apiUpload("/api/v1/settings/avatar-image", formData);
}

export async function testAvatar(text?: string): Promise<Response> {
  return apiFetch("/api/v1/settings/avatar-test", {
    method: "POST",
    body: JSON.stringify({ text: text ?? null }),
  });
}

export async function fetchVideoBlob(path: string): Promise<Blob> {
  const res = await checkedFetch(`${API_URL}${path}`, { headers: downloadHeaders() }, path);
  if (!res.ok) {
    throw new Error(await formatApiError(res, "Falha ao carregar vídeo"));
  }
  return res.blob();
}

export type {
  AvatarImageInfo,
  AvatarImageUploadResponse,
  AvatarTestResponse,
  SettingsResponse,
  VoiceSampleInfo,
  VoiceSampleUploadResponse,
  VoiceTestResponse,
};
