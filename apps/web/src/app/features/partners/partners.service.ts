import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  Partner,
  PartnerInput,
  PartnerPosting,
  PartnerStatement,
  PartnerSummary,
  PartnerTransaction,
  PartnerTransactionInput,
  PartnerUpdate,
  Preview,
  Share,
  ShareChangeInput,
} from '../../core/api/api.models';

/** Calls to the partner endpoints (docs/API.md §3.3). */
@Injectable({ providedIn: 'root' })
export class PartnersService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/partners`;

  list(includeArchived = false): Promise<Partner[]> {
    return firstValueFrom(
      this.http.get<Partner[]>(this.base, { params: new HttpParams().set('include_archived', includeArchived) }),
    );
  }

  get(id: string): Promise<Partner> {
    return firstValueFrom(this.http.get<Partner>(`${this.base}/${id}`));
  }

  create(body: PartnerInput): Promise<Partner> {
    return firstValueFrom(this.http.post<Partner>(this.base, body));
  }

  update(id: string, body: PartnerUpdate): Promise<Partner> {
    return firstValueFrom(this.http.patch<Partner>(`${this.base}/${id}`, body));
  }

  revealNationalId(id: string): Promise<string> {
    return firstValueFrom(this.http.get<{ national_id: string }>(`${this.base}/${id}/national-id`)).then(
      (r) => r.national_id,
    );
  }

  summary(asOf?: string): Promise<PartnerSummary> {
    const params = asOf ? new HttpParams().set('as_of', asOf) : undefined;
    return firstValueFrom(this.http.get<PartnerSummary>(`${this.base}/summary`, { params }));
  }

  shares(): Promise<Share[]> {
    return firstValueFrom(this.http.get<Share[]>(`${this.base}/shares`));
  }

  shareHistory(): Promise<Share[]> {
    return firstValueFrom(this.http.get<Share[]>(`${this.base}/shares/history`));
  }

  changeShares(body: ShareChangeInput): Promise<Share[]> {
    return firstValueFrom(this.http.post<Share[]>(`${this.base}/shares`, body));
  }

  previewTransaction(partnerId: string, body: PartnerTransactionInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/${partnerId}/transactions/preview`, body));
  }

  recordTransaction(partnerId: string, body: PartnerTransactionInput, idempotencyKey: string): Promise<PartnerPosting> {
    return firstValueFrom(
      this.http.post<PartnerPosting>(`${this.base}/${partnerId}/transactions`, body, {
        headers: { 'Idempotency-Key': idempotencyKey },
      }),
    );
  }

  transactions(partnerId: string): Promise<PartnerTransaction[]> {
    return firstValueFrom(this.http.get<PartnerTransaction[]>(`${this.base}/${partnerId}/transactions`));
  }

  statement(partnerId: string, dateFrom: string, dateTo: string): Promise<PartnerStatement> {
    return firstValueFrom(
      this.http.get<PartnerStatement>(`${this.base}/${partnerId}/statement`, {
        params: new HttpParams().set('date_from', dateFrom).set('date_to', dateTo),
      }),
    );
  }

  async downloadStatement(
    partnerId: string,
    dateFrom: string,
    dateTo: string,
    format: 'xlsx' | 'pdf',
    lang: 'ar' | 'en',
  ): Promise<void> {
    const response = await firstValueFrom(
      this.http.get(`${this.base}/${partnerId}/statement`, {
        params: new HttpParams()
          .set('date_from', dateFrom)
          .set('date_to', dateTo)
          .set('format', format)
          .set('lang', lang),
        responseType: 'blob',
        observe: 'response',
      }),
    );
    const disposition = response.headers.get('content-disposition') ?? '';
    const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `partner-statement.${format}`;
    const url = URL.createObjectURL(response.body as Blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }
}
