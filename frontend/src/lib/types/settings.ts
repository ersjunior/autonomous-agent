export type SettingFieldType =
  | "string"
  | "enum"
  | "secret"
  | "url"
  | "number"
  | "textarea";

export interface SettingField {
  key: string;
  label: string;
  type: SettingFieldType;
  options: string[] | null;
  is_secret: boolean;
  read_only: boolean;
  value: string | number | null;
  min?: number | null;
  max?: number | null;
  step?: number | null;
  max_length?: number | null;
  default_value?: string | null;
}

export interface SettingCategory {
  id: string;
  label: string;
  fields: SettingField[];
}

export interface SettingsResponse {
  categories: SettingCategory[];
  settings_version: number;
  runtime: Record<string, string | number | null>;
}

export interface VoiceSampleUploadResponse {
  filename: string;
  size_bytes: number;
  path: string;
  message: string;
}

export interface VoiceTestResponse {
  audio_url: string;
  filename: string;
}

export interface VoiceSampleInfo {
  exists: boolean;
  filename: string;
  size_bytes: number;
  modified_at: string | null;
  path: string;
}

export interface AvatarImageUploadResponse {
  filename: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  message: string;
}

export interface AvatarTestResponse {
  video_url: string;
  filename: string;
}

export interface AvatarImageInfo {
  exists: boolean;
  filename: string;
  size_bytes: number;
  modified_at: string | null;
  width: number | null;
  height: number | null;
}
