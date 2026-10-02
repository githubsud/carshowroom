import { Injectable, signal } from '@angular/core';

const LAST_TENANT_KEY = 'sayyara.lastTenantId';

/**
 * The active tenant id, kept free of dependencies so the HTTP interceptor can
 * read it without a circular injection through HttpClient.
 */
@Injectable({ providedIn: 'root' })
export class ActiveTenantStore {
  private readonly _tenantId = signal<string | null>(null);
  readonly tenantId = this._tenantId.asReadonly();

  set(tenantId: string | null): void {
    this._tenantId.set(tenantId);
    try {
      if (tenantId) {
        localStorage.setItem(LAST_TENANT_KEY, tenantId);
      }
    } catch {
      // Storage can be unavailable (private mode); remembering is a convenience only.
    }
  }

  lastUsed(): string | null {
    try {
      return localStorage.getItem(LAST_TENANT_KEY);
    } catch {
      return null;
    }
  }
}
