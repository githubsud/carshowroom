import { HttpClient } from '@angular/common/http';
import { computed, inject, Injectable, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { environment } from '../../../environments/environment';
import { Me, Membership, Tenant, TenantSettingsUpdate } from '../api/api.models';
import { ActiveTenantStore } from './active-tenant.store';

/**
 * Who the user is in which showroom: memberships, the active tenant, its
 * permissions and feature flags. The UI hides what a user may not do; the API
 * and RLS enforce it (SPEC §15).
 */
@Injectable({ providedIn: 'root' })
export class TenantContextService {
  private readonly http = inject(HttpClient);
  private readonly store = inject(ActiveTenantStore);

  private readonly _me = signal<Me | null>(null);
  private readonly _tenant = signal<Tenant | null>(null);
  private loading: Promise<Me> | null = null;

  readonly me = this._me.asReadonly();
  readonly tenant = this._tenant.asReadonly();
  readonly memberships = computed(() => this._me()?.memberships ?? []);
  readonly activeTenantId = this.store.tenantId;
  readonly active = computed<Membership | null>(
    () => this.memberships().find((m) => m.tenant_id === this.activeTenantId()) ?? null,
  );
  readonly permissions = computed(() => new Set(this.active()?.permissions ?? []));
  readonly flags = computed(() => this.active()?.feature_flags ?? {});

  can(permission: string): boolean {
    return this.permissions().has(permission);
  }

  canAny(permissions: readonly string[]): boolean {
    const held = this.permissions();
    return permissions.some((p) => held.has(p));
  }

  /** Loads /me once per session (or again when forced, e.g. after an invite is accepted). */
  ensureLoaded(force = false): Promise<Me> {
    if (!force && this._me()) {
      return Promise.resolve(this._me() as Me);
    }
    if (!this.loading) {
      this.loading = firstValueFrom(this.http.get<Me>(`${environment.apiBaseUrl}/me`))
        .then((me) => {
          this._me.set(me);
          return me;
        })
        .finally(() => (this.loading = null));
    }
    return this.loading;
  }

  /** Makes a tenant active; false if the user is not a member. */
  async activate(tenantId: string): Promise<boolean> {
    const me = await this.ensureLoaded();
    if (!me.memberships.some((m) => m.tenant_id === tenantId)) {
      return false;
    }
    if (this.activeTenantId() !== tenantId || !this._tenant()) {
      this.store.set(tenantId);
      this._tenant.set(null);
      this._tenant.set(await firstValueFrom(this.http.get<Tenant>(`${environment.apiBaseUrl}/tenant`)));
    }
    return true;
  }

  /** Change behavioural settings (Settings pages); the API checks tenant.settings.manage. */
  async updateSettings(changes: TenantSettingsUpdate): Promise<Tenant> {
    const tenant = await firstValueFrom(this.http.patch<Tenant>(`${environment.apiBaseUrl}/tenant/settings`, changes));
    this._tenant.set(tenant);
    return tenant;
  }

  /** The last tenant the user worked in, if they are still a member. */
  lastUsedTenantId(): string | null {
    const last = this.store.lastUsed();
    return last && this.memberships().some((m) => m.tenant_id === last) ? last : null;
  }

  clear(): void {
    this._me.set(null);
    this._tenant.set(null);
    this.store.set(null);
  }
}
