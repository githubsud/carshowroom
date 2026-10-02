import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { environment } from '../../../../environments/environment';
import { Member, Role } from '../../../core/api/api.models';

export interface InviteRequest {
  email: string;
  full_name?: string;
  role_code: string;
}

@Injectable({ providedIn: 'root' })
export class UsersService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  list(): Promise<Member[]> {
    return firstValueFrom(this.http.get<Member[]>(`${this.base}/users`));
  }

  roles(): Promise<Role[]> {
    return firstValueFrom(this.http.get<Role[]>(`${this.base}/roles`));
  }

  invite(request: InviteRequest): Promise<Member> {
    return firstValueFrom(this.http.post<Member>(`${this.base}/users/invite`, request));
  }

  update(membershipId: string, changes: { role_code?: string; status?: 'ACTIVE' | 'DISABLED' }): Promise<Member> {
    return firstValueFrom(this.http.patch<Member>(`${this.base}/users/${membershipId}`, changes));
  }
}
