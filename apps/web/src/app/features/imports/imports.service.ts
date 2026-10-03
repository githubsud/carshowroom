import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  EquityClearingInput,
  ImportCreateInput,
  ImportJob,
  ImportMappingInput,
  ImportPosting,
  OpeningEquity,
} from '../../core/api/api.models';
import { idempotent, toParams } from '../../shared/http-params';

/** Excel import and opening balances (docs/API.md §3.11). */
@Injectable({ providedIn: 'root' })
export class ImportsService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  template(lang: 'ar' | 'en'): Promise<Blob> {
    return firstValueFrom(this.http.get(`${this.base}/imports/template`, { params: toParams({ lang }), responseType: 'blob' }));
  }

  list(): Promise<ImportJob[]> {
    return firstValueFrom(this.http.get<ImportJob[]>(`${this.base}/imports`));
  }

  create(body: ImportCreateInput): Promise<ImportJob> {
    return firstValueFrom(this.http.post<ImportJob>(`${this.base}/imports`, body));
  }

  get(id: string): Promise<ImportJob> {
    return firstValueFrom(this.http.get<ImportJob>(`${this.base}/imports/${id}`));
  }

  setMapping(id: string, body: ImportMappingInput): Promise<ImportJob> {
    return firstValueFrom(this.http.put<ImportJob>(`${this.base}/imports/${id}/mapping`, body));
  }

  validate(id: string): Promise<ImportJob> {
    return firstValueFrom(this.http.post<ImportJob>(`${this.base}/imports/${id}/validate`, {}));
  }

  errors(id: string, lang: 'ar' | 'en'): Promise<Blob> {
    return firstValueFrom(
      this.http.get(`${this.base}/imports/${id}/errors`, { params: toParams({ lang }), responseType: 'blob' }),
    );
  }

  commit(id: string, key: string): Promise<ImportPosting> {
    return firstValueFrom(this.http.post<ImportPosting>(`${this.base}/imports/${id}/commit`, {}, idempotent(key)));
  }

  openingEquity(): Promise<OpeningEquity> {
    return firstValueFrom(this.http.get<OpeningEquity>(`${this.base}/opening-equity`));
  }

  clearOpeningEquity(body: EquityClearingInput, key: string): Promise<unknown> {
    return firstValueFrom(this.http.post(`${this.base}/opening-equity/clear`, body, idempotent(key)));
  }
}

/** A File as base64 (no data: prefix), for the JSON upload. */
export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '');
    reader.onerror = () => reject(reader.error ?? new Error('read failed'));
    reader.readAsDataURL(file);
  });
}
