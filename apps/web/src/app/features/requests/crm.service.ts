import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  CustomerRequest,
  CustomerRequestInput,
  CustomerRequestUpdate,
  FollowUp,
  FollowUpDue,
  FollowUpInput,
  RequestMatch,
} from '../../core/api/api.models';
import { toParams } from '../../shared/http-params';

/** Customer requests, matches and follow-ups (docs/API.md §3.9). */
@Injectable({ providedIn: 'root' })
export class CrmService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  requests(query: { status?: string | null; customer_id?: string | null; open_only?: boolean; q?: string | null } = {}): Promise<CustomerRequest[]> {
    return firstValueFrom(this.http.get<CustomerRequest[]>(`${this.base}/customer-requests`, { params: toParams(query) }));
  }

  request(id: string): Promise<CustomerRequest> {
    return firstValueFrom(this.http.get<CustomerRequest>(`${this.base}/customer-requests/${id}`));
  }

  createRequest(body: CustomerRequestInput): Promise<CustomerRequest> {
    return firstValueFrom(this.http.post<CustomerRequest>(`${this.base}/customer-requests`, body));
  }

  updateRequest(id: string, body: CustomerRequestUpdate): Promise<CustomerRequest> {
    return firstValueFrom(this.http.patch<CustomerRequest>(`${this.base}/customer-requests/${id}`, body));
  }

  vehicleMatches(vehicleId: string): Promise<RequestMatch[]> {
    return firstValueFrom(this.http.get<RequestMatch[]>(`${this.base}/vehicles/${vehicleId}/request-matches`));
  }

  setContacted(matchId: string, contacted: boolean): Promise<RequestMatch> {
    return firstValueFrom(this.http.put<RequestMatch>(`${this.base}/request-matches/${matchId}/contacted`, { contacted }));
  }

  followUps(customerId: string | null, limit = 50): Promise<FollowUp[]> {
    return firstValueFrom(
      this.http.get<FollowUp[]>(`${this.base}/follow-ups`, { params: toParams({ customer_id: customerId, limit }) }),
    );
  }

  dueFollowUps(mine = false): Promise<FollowUpDue[]> {
    return firstValueFrom(this.http.get<FollowUpDue[]>(`${this.base}/follow-ups/due`, { params: toParams({ mine }) }));
  }

  logFollowUp(body: FollowUpInput): Promise<FollowUp> {
    return firstValueFrom(this.http.post<FollowUp>(`${this.base}/follow-ups`, body));
  }
}
