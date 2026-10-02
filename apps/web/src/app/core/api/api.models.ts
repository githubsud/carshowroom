/**
 * API contracts used by the shell. From Phase 2 these come from the client
 * generated from the OpenAPI schema (BACKLOG 1.10); keep them in sync until then.
 */

export interface ApiErrorBody {
  error: { code: string; message: string; details: Record<string, unknown> };
}

/** An API error with its stable code; the UI translates the code (SPEC §8). */
export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

export interface Membership {
  tenant_id: string;
  tenant_name_ar: string;
  tenant_name_en: string | null;
  country_code: string;
  currency_code: string;
  timezone: string;
  role_code: string;
  partner_id: string | null;
  subscription_status: 'TRIAL' | 'ACTIVE' | 'PAST_DUE' | 'SUSPENDED';
  permissions: string[];
  feature_flags: Record<string, boolean>;
}

export interface Me {
  user: { id: string; email: string | null; full_name: string | null };
  is_platform_admin: boolean;
  memberships: Membership[];
}

export type DigitStyle = 'WESTERN' | 'ARABIC_INDIC';

export interface TenantSettings {
  default_language: 'ar' | 'en';
  digit_style: DigitStyle;
  [key: string]: unknown;
}

export interface Tenant {
  profile: {
    id: string;
    name_ar: string;
    name_en: string | null;
    country_code: string;
    currency_code: string;
    timezone: string;
  };
  settings: TenantSettings;
}

export interface Member {
  membership_id: string;
  user_id: string;
  email: string | null;
  full_name: string | null;
  role_code: string;
  status: 'ACTIVE' | 'DISABLED';
  partner_id: string | null;
  last_sign_in_at: string | null;
  created_at: string;
}

export interface Role {
  code: string;
  name_ar: string;
  name_en: string;
}
