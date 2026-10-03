import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  AttentionItem,
  Dashboard,
  Distribution,
  DistributionInput,
  DistributionPlan,
  DistributionPosting,
  LedgerAccount,
  ReportName,
  ReportTable,
} from '../../core/api/api.models';
import { idempotent, toParams } from '../../shared/http-params';

export interface ReportQuery {
  date_from?: string | null;
  date_to?: string | null;
  as_of?: string | null;
  account_id?: string | null;
}

/** Reports centre, dashboard, Needs Attention and profit distribution (docs/API.md §3.9, §3.10). */
@Injectable({ providedIn: 'root' })
export class ReportsService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  available(): Promise<ReportName[]> {
    return firstValueFrom(this.http.get<ReportName[]>(`${this.base}/reports`));
  }

  run(name: ReportName, query: ReportQuery): Promise<ReportTable> {
    return firstValueFrom(this.http.get<ReportTable>(`${this.base}/reports/${name}`, { params: toParams({ ...query }) }));
  }

  file(name: ReportName, query: ReportQuery, format: 'pdf' | 'xlsx', lang: 'ar' | 'en'): Promise<Blob> {
    return firstValueFrom(
      this.http.get(`${this.base}/reports/${name}`, { params: toParams({ ...query, format, lang }), responseType: 'blob' }),
    );
  }

  ledgerAccounts(): Promise<LedgerAccount[]> {
    return firstValueFrom(this.http.get<LedgerAccount[]>(`${this.base}/ledger-accounts`));
  }

  dashboard(): Promise<Dashboard> {
    return firstValueFrom(this.http.get<Dashboard>(`${this.base}/dashboard`));
  }

  attention(): Promise<AttentionItem[]> {
    return firstValueFrom(this.http.get<AttentionItem[]>(`${this.base}/attention`));
  }

  distributions(): Promise<Distribution[]> {
    return firstValueFrom(this.http.get<Distribution[]>(`${this.base}/distributions`));
  }

  previewDistribution(body: DistributionInput): Promise<DistributionPlan> {
    return firstValueFrom(this.http.post<DistributionPlan>(`${this.base}/distributions/preview`, body));
  }

  postDistribution(body: DistributionInput, key: string): Promise<DistributionPosting> {
    return firstValueFrom(this.http.post<DistributionPosting>(`${this.base}/distributions`, body, idempotent(key)));
  }

  reverseDistribution(id: string, reason: string): Promise<Distribution> {
    return firstValueFrom(this.http.post<Distribution>(`${this.base}/distributions/${id}/reverse`, { reason }));
  }
}
