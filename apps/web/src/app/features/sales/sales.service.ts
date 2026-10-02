import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  Preview,
  Reservation,
  ReservationInput,
  ReservationPosting,
  ReservationSettleInput,
  Sale,
  SaleCancelInput,
  SaleDraftInput,
  SalePage,
  SalePosting,
} from '../../core/api/api.models';
import { idempotent, toParams } from '../../shared/http-params';

/** Calls to the reservation and sale endpoints (docs/API.md §3.6). */
@Injectable({ providedIn: 'root' })
export class SalesService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  // --- Reservations ---------------------------------------------------------------------
  reservations(query: { status?: string; vehicle_id?: string }): Promise<Reservation[]> {
    return firstValueFrom(this.http.get<Reservation[]>(`${this.base}/reservations`, { params: toParams(query) }));
  }

  previewReservation(body: ReservationInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/reservations/preview`, body));
  }

  reserve(body: ReservationInput, key: string): Promise<ReservationPosting> {
    return firstValueFrom(this.http.post<ReservationPosting>(`${this.base}/reservations`, body, idempotent(key)));
  }

  previewSettle(id: string, body: ReservationSettleInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/reservations/${id}/settle/preview`, body));
  }

  settle(id: string, body: ReservationSettleInput, key: string): Promise<ReservationPosting> {
    return firstValueFrom(
      this.http.post<ReservationPosting>(`${this.base}/reservations/${id}/settle`, body, idempotent(key)),
    );
  }

  // --- Sales ------------------------------------------------------------------------------
  list(query: { status?: string | null; q?: string; page?: number; page_size?: number }): Promise<SalePage> {
    return firstValueFrom(this.http.get<SalePage>(`${this.base}/sales`, { params: toParams(query) }));
  }

  get(id: string): Promise<Sale> {
    return firstValueFrom(this.http.get<Sale>(`${this.base}/sales/${id}`));
  }

  createDraft(body: SaleDraftInput): Promise<Sale> {
    return firstValueFrom(this.http.post<Sale>(`${this.base}/sales`, body));
  }

  updateDraft(id: string, body: SaleDraftInput): Promise<Sale> {
    return firstValueFrom(this.http.put<Sale>(`${this.base}/sales/${id}`, body));
  }

  deleteDraft(id: string): Promise<unknown> {
    return firstValueFrom(this.http.delete(`${this.base}/sales/${id}`));
  }

  previewPost(id: string): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/sales/${id}/post/preview`, {}));
  }

  post(id: string, key: string): Promise<SalePosting> {
    return firstValueFrom(this.http.post<SalePosting>(`${this.base}/sales/${id}/post`, {}, idempotent(key)));
  }

  previewCancel(id: string, body: SaleCancelInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/sales/${id}/cancel/preview`, body));
  }

  cancel(id: string, body: SaleCancelInput, key: string): Promise<SalePosting> {
    return firstValueFrom(this.http.post<SalePosting>(`${this.base}/sales/${id}/cancel`, body, idempotent(key)));
  }

  document(id: string, kind: 'invoice' | 'contract', lang: 'ar' | 'en'): Promise<Blob> {
    return firstValueFrom(
      this.http.get(`${this.base}/sales/${id}/document`, { params: toParams({ kind, lang }), responseType: 'blob' }),
    );
  }
}
