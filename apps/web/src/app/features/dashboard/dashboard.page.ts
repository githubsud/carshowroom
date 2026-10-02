import { Component, computed, inject } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { CardModule } from 'primeng/card';
import { TagModule } from 'primeng/tag';

import { LanguageService } from '../../core/i18n/language.service';
import { TenantContextService } from '../../core/tenant/tenant-context.service';

/**
 * Phase 1 dashboard: who you are in which showroom. The financial dashboard
 * and Needs Attention panel arrive in Phase 7.
 */
@Component({
  selector: 'app-dashboard-page',
  imports: [TranslocoPipe, CardModule, TagModule],
  template: `
    <h1 class="page-title" data-testid="dashboard-title">{{ 'dashboard.welcome' | transloco: { name: tenantName() } }}</h1>

    <div class="grid">
      <p-card>
        <div class="kv">
          <span>{{ 'dashboard.yourRole' | transloco }}</span>
          <p-tag data-testid="role" [value]="'roles.' + (context.active()?.role_code ?? '') | transloco" />
        </div>
        <div class="kv">
          <span>{{ 'dashboard.subscription' | transloco }}</span>
          <span>{{ 'subscription.' + (context.active()?.subscription_status ?? '') | transloco }}</span>
        </div>
        <div class="kv">
          <span>{{ 'dashboard.currency' | transloco }}</span>
          <span>{{ context.active()?.currency_code }}</span>
        </div>
      </p-card>

      <p-card>
        <p class="muted">{{ 'dashboard.comingNext' | transloco }}</p>
      </p-card>
    </div>
  `,
  styles: `
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(320px, 100%), 1fr));
      gap: var(--space-3);
    }

    .kv {
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-block-size: 40px;
    }

    .muted {
      margin: 0;
      color: var(--color-text-muted);
    }
  `,
})
export class DashboardPage {
  protected readonly context = inject(TenantContextService);
  private readonly language = inject(LanguageService);

  protected readonly tenantName = computed(() => {
    const active = this.context.active();
    return this.language.language() === 'en' && active?.tenant_name_en ? active.tenant_name_en : (active?.tenant_name_ar ?? '');
  });
}
