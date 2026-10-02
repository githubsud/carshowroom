import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  Preview,
  Supplier,
  SupplierInput,
  SupplierPaymentInput,
  SupplierPaymentPosting,
  SupplierStatement,
} from '../../core/api/api.models';
import { idempotent, toParams } from '../../shared/http-params';

/** Calls to the supplier endpoints (D-23, rules 31, 32). */
@Injectable({ providedIn: 'root' })
export class SuppliersService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/suppliers`;

  list(includeArchived = false): Promise<Supplier[]> {
    return firstValueFrom(this.http.get<Supplier[]>(this.base, { params: toParams({ include_archived: includeArchived }) }));
  }

  create(body: SupplierInput): Promise<Supplier> {
    return firstValueFrom(this.http.post<Supplier>(this.base, body));
  }

  update(id: string, body: Partial<SupplierInput> & { archived?: boolean }): Promise<Supplier> {
    return firstValueFrom(this.http.patch<Supplier>(`${this.base}/${id}`, body));
  }

  statement(id: string, dateFrom: string, dateTo: string): Promise<SupplierStatement> {
    return firstValueFrom(
      this.http.get<SupplierStatement>(`${this.base}/${id}/statement`, {
        params: toParams({ date_from: dateFrom, date_to: dateTo }),
      }),
    );
  }

  previewPayment(id: string, body: SupplierPaymentInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/${id}/payments/preview`, body));
  }

  recordPayment(id: string, body: SupplierPaymentInput, key: string): Promise<SupplierPaymentPosting> {
    return firstValueFrom(this.http.post<SupplierPaymentPosting>(`${this.base}/${id}/payments`, body, idempotent(key)));
  }
}
