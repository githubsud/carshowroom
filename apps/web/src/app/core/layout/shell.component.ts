import { Component, computed, effect, inject, signal } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { DrawerModule } from 'primeng/drawer';
import { TagModule } from 'primeng/tag';

import { AuthService } from '../auth/auth.service';
import { PRODUCT_NAME, PRODUCT_NAME_AR } from '../config/product';
import { LanguageService } from '../i18n/language.service';
import { TenantContextService } from '../tenant/tenant-context.service';
import { GlobalSearchComponent } from './global-search.component';
import { visibleMenu } from './menu';

/** App frame: top bar, side navigation (desktop), bottom bar + drawer (mobile). */
@Component({
  selector: 'app-shell',
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    TranslocoPipe,
    ButtonModule,
    DrawerModule,
    TagModule,
    GlobalSearchComponent,
  ],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss',
})
export class ShellComponent {
  protected readonly context = inject(TenantContextService);
  protected readonly language = inject(LanguageService);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly email = this.auth.email;
  protected readonly menuOpen = signal(false);
  /** Set when the user signs out, so the session-ended redirect below stays quiet. */
  private leaving = false;
  protected readonly menu = computed(() => visibleMenu(this.context.permissions(), this.context.flags()));
  protected readonly primaryMenu = computed(() => this.menu().filter((item) => item.primary));
  protected readonly productName = computed(() => (this.language.language() === 'ar' ? PRODUCT_NAME_AR : PRODUCT_NAME));
  protected readonly tenantName = computed(() => {
    const active = this.context.active();
    if (!active) {
      return '';
    }
    return this.language.language() === 'en' && active.tenant_name_en ? active.tenant_name_en : active.tenant_name_ar;
  });
  protected readonly readOnly = computed(() => this.context.active()?.subscription_status === 'SUSPENDED');
  protected readonly hasSeveralTenants = computed(() => this.context.memberships().length > 1);

  constructor() {
    // Session ended elsewhere (expired, revoked, signed out in another tab):
    // back to login, returning here afterwards.
    effect(() => {
      if (!this.auth.isSignedIn() && !this.leaving) {
        void this.router.navigate(['/login'], { queryParams: { returnUrl: this.router.url } });
      }
    });

    // The tenant's default language applies until the user picks one.
    effect(() => {
      const language = this.context.tenant()?.settings.default_language;
      if (language) {
        this.language.applyTenantDefault(language);
      }
    });
  }

  /** Menu paths may contain slashes ("settings/users"), so links are built as strings. */
  protected link(path: string): string {
    return `/t/${this.context.activeTenantId() ?? ''}/${path}`;
  }

  protected async signOut(): Promise<void> {
    this.leaving = true;
    await this.auth.signOut();
    this.context.clear();
    await this.router.navigate(['/login']);
  }
}
