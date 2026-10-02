import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  Customer,
  CustomerDetail,
  CustomerInput,
  CustomerPage,
  CustomerRefundInput,
  CustomerRefundPosting,
  CustomerUpdate,
  Preview,
} from '../../core/api/api.models';
import { idempotent, toParams } from '../../shared/http-params';

/** Calls to the customer endpoints (docs/API.md §3.5). */
@Injectable({ providedIn: 'root' })
export class CustomersService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/customers`;

  list(query: { q?: string; role?: string | null; page?: number; page_size?: number }): Promise<CustomerPage> {
    return firstValueFrom(this.http.get<CustomerPage>(this.base, { params: toParams(query) }));
  }

  get(id: string): Promise<CustomerDetail> {
    return firstValueFrom(this.http.get<CustomerDetail>(`${this.base}/${id}`));
  }

  create(body: CustomerInput): Promise<Customer> {
    return firstValueFrom(this.http.post<Customer>(this.base, body));
  }

  update(id: string, body: CustomerUpdate): Promise<Customer> {
    return firstValueFrom(this.http.patch<Customer>(`${this.base}/${id}`, body));
  }

  nationalId(id: string): Promise<{ national_id: string }> {
    return firstValueFrom(this.http.get<{ national_id: string }>(`${this.base}/${id}/national-id`));
  }

  previewRefund(id: string, body: CustomerRefundInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/${id}/refunds/preview`, body));
  }

  recordRefund(id: string, body: CustomerRefundInput, key: string): Promise<CustomerRefundPosting> {
    return firstValueFrom(this.http.post<CustomerRefundPosting>(`${this.base}/${id}/refunds`, body, idempotent(key)));
  }
}
