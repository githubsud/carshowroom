import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { environment } from '../../../environments/environment';
import { ApiError } from '../api/api.models';
import { AuthService } from '../auth/auth.service';
import { ActiveTenantStore } from '../tenant/active-tenant.store';
import { apiInterceptor } from './api.interceptor';

const flush = () => new Promise((resolve) => setTimeout(resolve));

describe('apiInterceptor', () => {
  let http: HttpClient;
  let backend: HttpTestingController;
  const auth = {
    accessToken: vi.fn(),
    refresh: vi.fn(),
    signOut: vi.fn(),
  };

  beforeEach(() => {
    auth.accessToken.mockResolvedValue('token-1');
    auth.refresh.mockResolvedValue('token-2');
    auth.signOut.mockResolvedValue(undefined);
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(withInterceptors([apiInterceptor])),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: auth },
      ],
    });
    http = TestBed.inject(HttpClient);
    backend = TestBed.inject(HttpTestingController);
    TestBed.inject(ActiveTenantStore).set('tenant-a');
  });

  it('adds the bearer token and the active tenant to API calls', async () => {
    const result = firstValueFrom(http.get(`${environment.apiBaseUrl}/tenant`));
    await flush();
    const req = backend.expectOne(`${environment.apiBaseUrl}/tenant`);
    expect(req.request.headers.get('Authorization')).toBe('Bearer token-1');
    expect(req.request.headers.get('X-Tenant-Id')).toBe('tenant-a');
    req.flush({ ok: true });
    await expect(result).resolves.toEqual({ ok: true });
  });

  it('leaves other hosts untouched', async () => {
    const result = firstValueFrom(http.get('/i18n/ar.json'));
    const req = backend.expectOne('/i18n/ar.json');
    expect(req.request.headers.has('Authorization')).toBe(false);
    expect(req.request.headers.has('X-Tenant-Id')).toBe(false);
    req.flush({});
    await result;
  });

  it('refreshes the session once on 401 and retries', async () => {
    const result = firstValueFrom(http.get(`${environment.apiBaseUrl}/me`));
    await flush();
    backend
      .expectOne(`${environment.apiBaseUrl}/me`)
      .flush({ error: { code: 'AUTH_INVALID_TOKEN', message: 'expired', details: {} } }, { status: 401, statusText: 'Unauthorized' });
    await flush();
    const retry = backend.expectOne(`${environment.apiBaseUrl}/me`);
    expect(retry.request.headers.get('Authorization')).toBe('Bearer token-2');
    retry.flush({ user: {} });
    await expect(result).resolves.toEqual({ user: {} });
  });

  it('turns API error bodies into ApiError with the code', async () => {
    const result = firstValueFrom(http.patch(`${environment.apiBaseUrl}/tenant/settings`, {}));
    await flush();
    backend.expectOne(`${environment.apiBaseUrl}/tenant/settings`).flush(
      { error: { code: 'PERMISSION_DENIED', message: 'Missing permission', details: { permission: 'tenant.settings.manage' } } },
      { status: 403, statusText: 'Forbidden' },
    );
    const error = await result.catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe('PERMISSION_DENIED');
    expect((error as ApiError).details).toEqual({ permission: 'tenant.settings.manage' });
  });
});
