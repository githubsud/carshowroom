import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { CardModule } from 'primeng/card';
import { TagModule } from 'primeng/tag';

import { PartnerStatement } from '../../core/api/api.models';
import { FormatService, MoneyPipe } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { PartnersService } from '../partners/partners.service';
import { TenantContextService } from '../../core/tenant/tenant-context.service';

/**
 * Phase 1 dashboard: who you are in which showroom. The financial dashboard
 * and Needs Attention panel arrive in Phase 7.
 */
@Component({
  selector: 'app-dashboard-page',
  imports: [TranslocoPipe, CardModule, TagModule, RouterLink, MoneyPipe],
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

      @if (myPosition(); as s) {
        <p-card data-testid="my-position">
          <div class="kv"><strong>{{ 'dashboard.myPosition' | transloco }}</strong></div>
          <div class="kv"><span>{{ 'partners.capital' | transloco }}</span><span>{{ s.closing.capital | money }}</span></div>
          <div class="kv"><span>{{ 'partners.current' | transloco }}</span><span>{{ s.closing.current | money }}</span></div>
          <div class="kv"><span>{{ 'partners.net' | transloco }}</span><strong>{{ s.closing.net | money }}</strong></div>
          <a [routerLink]="['/t', context.activeTenantId(), 'partners', s.partner.id]">{{ 'dashboard.openStatement' | transloco }}</a>
        </p-card>
      }

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
export class DashboardPage implements OnInit {
  protected readonly context = inject(TenantContextService);
  private readonly language = inject(LanguageService);
  private readonly partners = inject(PartnersService);
  private readonly format = inject(FormatService);

  /** A partner sees their own position at a glance (SPEC §1.2). */
  protected readonly myPosition = signal<PartnerStatement | null>(null);

  ngOnInit(): void {
    const partnerId = this.context.active()?.partner_id;
    if (partnerId && (this.context.can('partner.view_own') || this.context.can('partner.view_all'))) {
      const today = this.format.todayIso();
      void this.partners
        .statement(partnerId, today, today)
        .then((s) => this.myPosition.set(s))
        .catch(() => this.myPosition.set(null));
    }
  }

  protected readonly tenantName = computed(() => {
    const active = this.context.active();
    return this.language.language() === 'en' && active?.tenant_name_en ? active.tenant_name_en : (active?.tenant_name_ar ?? '');
  });
}
