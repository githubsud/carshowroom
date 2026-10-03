import { computed, inject, Injectable, signal } from '@angular/core';
import type { AuthChangeEvent, Session } from '@supabase/supabase-js';

import { SupabaseService } from '../supabase/supabase.service';

/** Supabase Auth session as signals. */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly supabase = inject(SupabaseService).client;

  private readonly _session = signal<Session | null>(null);
  private readonly _lastEvent = signal<AuthChangeEvent | null>(null);
  readonly session = this._session.asReadonly();
  readonly lastEvent = this._lastEvent.asReadonly();
  readonly isSignedIn = computed(() => this._session() !== null);
  readonly email = computed(() => this._session()?.user.email ?? null);

  /** Resolves once the stored session (if any) has been restored. */
  readonly ready: Promise<void>;

  constructor() {
    this.ready = this.supabase.auth.getSession().then(({ data }) => this._session.set(data.session));
    this.supabase.auth.onAuthStateChange((event, session) => {
      this._lastEvent.set(event);
      this._session.set(session);
    });
  }

  async signIn(email: string, password: string): Promise<void> {
    const { data, error } = await this.supabase.auth.signInWithPassword({ email, password });
    if (error) {
      throw error;
    }
    this._session.set(data.session);
  }

  /**
   * Self-serve signup (SPEC §4.16): the account first, then the showroom.
   * Returns false when the project asks to confirm the email first (hosted
   * Supabase, D-118): the user follows the link, then signs in.
   */
  async signUp(email: string, password: string, fullName: string): Promise<boolean> {
    const { data, error } = await this.supabase.auth.signUp({
      email,
      password,
      options: { data: { full_name: fullName }, emailRedirectTo: `${window.location.origin}/login` },
    });
    if (error) {
      throw error;
    }
    this._session.set(data.session);
    return data.session !== null;
  }

  // --- Two-step sign-in (TOTP, D-119) ---------------------------------------------------

  /** True when the account has an authenticator and this session has not used it yet. */
  async needsSecondStep(): Promise<boolean> {
    const { data } = await this.supabase.auth.mfa.getAuthenticatorAssuranceLevel();
    return data?.nextLevel === 'aal2' && data.currentLevel !== 'aal2';
  }

  async verifySecondStep(code: string): Promise<void> {
    const { data: factors, error: listError } = await this.supabase.auth.mfa.listFactors();
    if (listError) {
      throw listError;
    }
    const factor = factors.totp[0];
    if (!factor) {
      throw new Error('no authenticator');
    }
    const { error } = await this.supabase.auth.mfa.challengeAndVerify({ factorId: factor.id, code });
    if (error) {
      throw error;
    }
    await this.refresh();
  }

  async factors(): Promise<{ id: string; friendly_name?: string; status: string }[]> {
    const { data, error } = await this.supabase.auth.mfa.listFactors();
    if (error) {
      throw error;
    }
    return data.all;
  }

  async enroll(): Promise<{ factorId: string; qr: string; secret: string }> {
    const { data, error } = await this.supabase.auth.mfa.enroll({ factorType: 'totp', friendlyName: 'Sayyara' });
    if (error) {
      throw error;
    }
    return { factorId: data.id, qr: data.totp.qr_code, secret: data.totp.secret };
  }

  async confirmEnroll(factorId: string, code: string): Promise<void> {
    const { error } = await this.supabase.auth.mfa.challengeAndVerify({ factorId, code });
    if (error) {
      throw error;
    }
    await this.refresh();
  }

  async unenroll(factorId: string): Promise<void> {
    const { error } = await this.supabase.auth.mfa.unenroll({ factorId });
    if (error) {
      throw error;
    }
    await this.refresh();
  }

  /** Signs out this device only; other devices (e.g. the owner's phone) stay signed in. */
  async signOut(): Promise<void> {
    await this.supabase.auth.signOut({ scope: 'local' });
    // Data read offline belongs to this user: forget it.
    navigator.serviceWorker?.controller?.postMessage('clear-api-cache');
    this._session.set(null);
  }

  async sendPasswordReset(email: string, redirectTo: string): Promise<void> {
    const { error } = await this.supabase.auth.resetPasswordForEmail(email, { redirectTo });
    if (error) {
      throw error;
    }
  }

  async updatePassword(password: string): Promise<void> {
    const { error } = await this.supabase.auth.updateUser({ password });
    if (error) {
      throw error;
    }
  }

  /** A valid access token, refreshed by supabase-js when close to expiry. */
  async accessToken(): Promise<string | null> {
    const { data } = await this.supabase.auth.getSession();
    return data.session?.access_token ?? null;
  }

  async refresh(): Promise<string | null> {
    const { data } = await this.supabase.auth.refreshSession();
    this._session.set(data.session);
    return data.session?.access_token ?? null;
  }
}
