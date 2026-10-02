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

  /** Signs out this device only; other devices (e.g. the owner's phone) stay signed in. */
  async signOut(): Promise<void> {
    await this.supabase.auth.signOut({ scope: 'local' });
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
