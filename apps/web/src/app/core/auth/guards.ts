import { inject } from '@angular/core';
import { ActivatedRouteSnapshot, CanActivateFn, Router, RouterStateSnapshot } from '@angular/router';

import { TenantContextService } from '../tenant/tenant-context.service';
import { AuthService } from './auth.service';

// Note: in async guards every inject() must run before the first await; after
// it the injection context is gone (NG0203).

/** Signed-in users only; others go to login and come back afterwards. */
export const authGuard: CanActivateFn = async (_route, state: RouterStateSnapshot) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  await auth.ready;
  if (auth.isSignedIn()) {
    return true;
  }
  return router.createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
};

/** Login pages are skipped when already signed in. */
export const guestGuard: CanActivateFn = async () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  await auth.ready;
  return auth.isSignedIn() ? router.createUrlTree(['/tenants']) : true;
};

/** /t/:tenantId/** — the user must be an active member of that tenant. */
export const tenantGuard: CanActivateFn = async (route: ActivatedRouteSnapshot) => {
  const auth = inject(AuthService);
  const context = inject(TenantContextService);
  const router = inject(Router);
  await auth.ready;
  if (!auth.isSignedIn()) {
    return false; // authGuard (listed first) redirects to login.
  }
  const tenantId = route.paramMap.get('tenantId');
  try {
    if (tenantId && (await context.activate(tenantId))) {
      return true;
    }
  } catch {
    // API unreachable or session rejected: fall through to the switcher, which shows the error.
  }
  return router.createUrlTree(['/tenants']);
};

/** Feature routes: the active membership must hold at least one of the permissions. */
export function permissionGuard(...anyOf: string[]): CanActivateFn {
  return () => {
    const context = inject(TenantContextService);
    if (context.canAny(anyOf)) {
      return true;
    }
    return inject(Router).createUrlTree(['/t', context.activeTenantId(), 'dashboard']);
  };
}
