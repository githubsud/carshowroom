import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  Consignment,
  ConsignmentInput,
  ConsignmentOutPosting,
  ConsignmentOutRow,
  ConsignmentPosting,
  ConsignmentReturnInput,
  ConsignorSettlementInput,
  ConsignorStatement,
  ConsignOutInput,
  ExternalCollectionInput,
  ExternalCollectionPosting,
  ExternalSaleInput,
  ExternalShowroom,
  ExternalShowroomInput,
  ExternalShowroomStatement,
  Preview,
} from '../../core/api/api.models';
import { idempotent, toParams } from '../../shared/http-params';

/** Calls to the consignment and external showroom endpoints (docs/API.md §3.8). */
@Injectable({ providedIn: 'root' })
export class ConsignmentService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  // --- External showrooms ---------------------------------------------------------------
  showrooms(includeArchived = false): Promise<ExternalShowroom[]> {
    return firstValueFrom(
      this.http.get<ExternalShowroom[]>(`${this.base}/external-showrooms`, {
        params: toParams({ include_archived: includeArchived }),
      }),
    );
  }

  createShowroom(body: ExternalShowroomInput): Promise<ExternalShowroom> {
    return firstValueFrom(this.http.post<ExternalShowroom>(`${this.base}/external-showrooms`, body));
  }

  showroomStatement(id: string): Promise<ExternalShowroomStatement> {
    return firstValueFrom(this.http.get<ExternalShowroomStatement>(`${this.base}/external-showrooms/${id}/statement`));
  }

  showroomStatementPdf(id: string, lang: 'ar' | 'en'): Promise<Blob> {
    return firstValueFrom(
      this.http.get(`${this.base}/external-showrooms/${id}/statement`, {
        params: toParams({ format: 'pdf', lang }),
        responseType: 'blob',
      }),
    );
  }

  previewCollection(id: string, body: ExternalCollectionInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/external-showrooms/${id}/collections/preview`, body));
  }

  recordCollection(id: string, body: ExternalCollectionInput, key: string): Promise<ExternalCollectionPosting> {
    return firstValueFrom(
      this.http.post<ExternalCollectionPosting>(`${this.base}/external-showrooms/${id}/collections`, body, idempotent(key)),
    );
  }

  // --- Consignment IN ------------------------------------------------------------------
  list(query: { status?: string | null; consignor_id?: string | null; q?: string | null } = {}): Promise<Consignment[]> {
    return firstValueFrom(this.http.get<Consignment[]>(`${this.base}/consignments`, { params: toParams(query) }));
  }

  get(id: string): Promise<Consignment> {
    return firstValueFrom(this.http.get<Consignment>(`${this.base}/consignments/${id}`));
  }

  create(body: ConsignmentInput): Promise<Consignment> {
    return firstValueFrom(this.http.post<Consignment>(`${this.base}/consignments`, body));
  }

  returnToOwner(id: string, body: ConsignmentReturnInput): Promise<Consignment> {
    return firstValueFrom(this.http.post<Consignment>(`${this.base}/consignments/${id}/return`, body));
  }

  agreementPdf(id: string, lang: 'ar' | 'en'): Promise<Blob> {
    return firstValueFrom(
      this.http.get(`${this.base}/consignments/${id}/agreement`, { params: toParams({ lang }), responseType: 'blob' }),
    );
  }

  previewSettlement(id: string, body: ConsignorSettlementInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/consignments/${id}/settlements/preview`, body));
  }

  recordSettlement(id: string, body: ConsignorSettlementInput, key: string): Promise<ConsignmentPosting> {
    return firstValueFrom(
      this.http.post<ConsignmentPosting>(`${this.base}/consignments/${id}/settlements`, body, idempotent(key)),
    );
  }

  consignorStatement(customerId: string): Promise<ConsignorStatement> {
    return firstValueFrom(this.http.get<ConsignorStatement>(`${this.base}/customers/${customerId}/consignor-statement`));
  }

  consignorStatementPdf(customerId: string, lang: 'ar' | 'en'): Promise<Blob> {
    return firstValueFrom(
      this.http.get(`${this.base}/customers/${customerId}/consignor-statement`, {
        params: toParams({ format: 'pdf', lang }),
        responseType: 'blob',
      }),
    );
  }

  // --- Consignment OUT -----------------------------------------------------------------
  listOut(query: { status?: string | null; external_showroom_id?: string | null } = {}): Promise<ConsignmentOutRow[]> {
    return firstValueFrom(this.http.get<ConsignmentOutRow[]>(`${this.base}/consignments-out`, { params: toParams(query) }));
  }

  consignOut(body: ConsignOutInput): Promise<ConsignmentOutRow> {
    return firstValueFrom(this.http.post<ConsignmentOutRow>(`${this.base}/consignments-out`, body));
  }

  returnOut(id: string, returnDate: string, reason: string | null): Promise<ConsignmentOutRow> {
    return firstValueFrom(
      this.http.post<ConsignmentOutRow>(`${this.base}/consignments-out/${id}/return`, { return_date: returnDate, reason }),
    );
  }

  previewExternalSale(id: string, body: ExternalSaleInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/consignments-out/${id}/sale/preview`, body));
  }

  recordExternalSale(id: string, body: ExternalSaleInput, key: string): Promise<ConsignmentOutPosting> {
    return firstValueFrom(
      this.http.post<ConsignmentOutPosting>(`${this.base}/consignments-out/${id}/sale`, body, idempotent(key)),
    );
  }
}
