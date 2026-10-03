import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  AuditPage,
  Branch,
  Invoice,
  PlatformTenant,
  PlatformTenantUpdate,
  SupportGrant,
  SupportSummary,
  Usage,
} from '../../core/api/api.models';
import { toParams } from '../../shared/http-params';

/** The SaaS layer (docs/API.md §3.13): super admin console and tenant-side settings. */
@Injectable({ providedIn: 'root' })
export class PlatformService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  // --- Super admin (no tenant header) ---
  tenants(): Promise<PlatformTenant[]> {
    return firstValueFrom(this.http.get<PlatformTenant[]>(`${this.base}/admin/tenants`));
  }

  updateTenant(id: string, body: PlatformTenantUpdate): Promise<PlatformTenant> {
    return firstValueFrom(this.http.patch<PlatformTenant>(`${this.base}/admin/tenants/${id}`, body));
  }

  invoices(id: string): Promise<Invoice[]> {
    return firstValueFrom(this.http.get<Invoice[]>(`${this.base}/admin/tenants/${id}/invoices`));
  }

  issueInvoice(id: string, body: { period_start: string; period_end: string; amount: string }): Promise<Invoice> {
    return firstValueFrom(this.http.post<Invoice>(`${this.base}/admin/tenants/${id}/invoices`, body));
  }

  markPaid(tenantId: string, invoiceId: string, reference: string | null): Promise<Invoice> {
    return firstValueFrom(
      this.http.post<Invoice>(`${this.base}/admin/tenants/${tenantId}/invoices/${invoiceId}/paid`, { reference }),
    );
  }

  support(id: string): Promise<SupportSummary> {
    return firstValueFrom(this.http.get<SupportSummary>(`${this.base}/admin/tenants/${id}/support`));
  }

  // --- Signup ---
  signup(body: { name_ar: string; name_en: string | null; country_code: 'EG' | 'QA' }): Promise<{ tenant_id: string }> {
    return firstValueFrom(this.http.post<{ tenant_id: string }>(`${this.base}/signup`, body));
  }

  // --- Tenant side ---
  usage(): Promise<Usage> {
    return firstValueFrom(this.http.get<Usage>(`${this.base}/usage`));
  }

  branches(): Promise<Branch[]> {
    return firstValueFrom(this.http.get<Branch[]>(`${this.base}/branches`));
  }

  addBranch(body: { name_ar: string; name_en: string | null; address: string | null }): Promise<Branch> {
    return firstValueFrom(this.http.post<Branch>(`${this.base}/branches`, body));
  }

  grants(): Promise<SupportGrant[]> {
    return firstValueFrom(this.http.get<SupportGrant[]>(`${this.base}/support-grants`));
  }

  grant(hours: number, reason: string): Promise<SupportGrant> {
    return firstValueFrom(this.http.post<SupportGrant>(`${this.base}/support-grants`, { hours, reason }));
  }

  revoke(id: string): Promise<SupportGrant> {
    return firstValueFrom(this.http.post<SupportGrant>(`${this.base}/support-grants/${id}/revoke`, {}));
  }

  audit(query: Record<string, string | number | null>): Promise<AuditPage> {
    return firstValueFrom(this.http.get<AuditPage>(`${this.base}/audit`, { params: toParams(query) }));
  }

  export(): Promise<Blob> {
    return firstValueFrom(this.http.get(`${this.base}/tenant/export`, { responseType: 'blob' }));
  }
}
