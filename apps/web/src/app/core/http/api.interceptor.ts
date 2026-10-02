import { HttpErrorResponse, HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, from, switchMap, throwError } from 'rxjs';

import { environment } from '../../../environments/environment';
import { ApiError, ApiErrorBody } from '../api/api.models';
import { AuthService } from '../auth/auth.service';
import { ActiveTenantStore } from '../tenant/active-tenant.store';

function withHeaders(req: HttpRequest<unknown>, token: string | null, tenantId: string | null): HttpRequest<unknown> {
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  if (tenantId) {
    headers['X-Tenant-Id'] = tenantId;
  }
  return req.clone({ setHeaders: headers });
}

/** Converts any HTTP failure into an ApiError carrying the API's error code. */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  if (error instanceof HttpErrorResponse) {
    const body = error.error as Partial<ApiErrorBody> | null;
    if (body?.error?.code) {
      return new ApiError(body.error.code, body.error.message, error.status, body.error.details ?? {});
    }
    return new ApiError(error.status === 0 ? 'NETWORK_ERROR' : 'HTTP_ERROR', error.message, error.status);
  }
  return new ApiError('UNKNOWN_ERROR', String(error), 0);
}

/**
 * For calls to our API: attach the Supabase access token and the active
 * X-Tenant-Id (SPEC §9.1), retry once after a token refresh on 401, and turn
 * failures into ApiError codes the UI translates.
 */
export const apiInterceptor: HttpInterceptorFn = (req, next) => {
  if (!req.url.startsWith(environment.apiBaseUrl)) {
    return next(req);
  }
  const auth = inject(AuthService);
  const tenant = inject(ActiveTenantStore);

  return from(auth.accessToken()).pipe(
    switchMap((token) => next(withHeaders(req, token, tenant.tenantId()))),
    catchError((error: unknown) => {
      if (!(error instanceof HttpErrorResponse) || error.status !== 401) {
        return throwError(() => error);
      }
      return from(auth.refresh()).pipe(
        switchMap((token) => {
          if (!token) {
            // The session is gone; guards and the shell send the user to login.
            void auth.signOut();
            return throwError(() => error);
          }
          return next(withHeaders(req, token, tenant.tenantId()));
        }),
      );
    }),
    catchError((error: unknown) => throwError(() => toApiError(error))),
  );
};
