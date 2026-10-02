import { Directive, effect, inject, input, TemplateRef, ViewContainerRef } from '@angular/core';

import { TenantContextService } from '../tenant/tenant-context.service';

/**
 * Renders its content only if the active membership holds the permission
 * (or any of a list): `<button *appCan="'users.manage'">`.
 * UI convenience only; the API and RLS enforce access.
 */
@Directive({ selector: '[appCan]' })
export class CanDirective {
  private readonly context = inject(TenantContextService);
  private readonly template = inject(TemplateRef<unknown>);
  private readonly container = inject(ViewContainerRef);
  private rendered = false;

  readonly appCan = input.required<string | readonly string[]>();

  constructor() {
    effect(() => {
      const wanted = this.appCan();
      const allowed = this.context.canAny(typeof wanted === 'string' ? [wanted] : wanted);
      if (allowed && !this.rendered) {
        this.container.createEmbeddedView(this.template);
        this.rendered = true;
      } else if (!allowed && this.rendered) {
        this.container.clear();
        this.rendered = false;
      }
    });
  }
}
