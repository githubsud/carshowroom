import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { CardModule } from 'primeng/card';
import { TagModule } from 'primeng/tag';

import { AttentionItem, Dashboard, EquityRow, PartnerStatement } from '../../core/api/api.models';
import { FormatService, MoneyPipe } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { PartnersService } from '../partners/partners.service';
import { ReportsService } from '../reports/reports.service';

const ICONS: Record<string, string> = {
  INSTALLMENT_OVERDUE: 'pi-exclamation-circle',
  INSTALLMENT_DUE_SOON: 'pi-calendar',
  CHEQUE_BOUNCED: 'pi-times-circle',
  VEHICLE_AGING: 'pi-clock',
  LICENSE_EXPIRY: 'pi-id-card',
  COST_INCOMPLETE: 'pi-list-check',
  LOW_PROFIT: 'pi-arrow-down',
  REQUEST_MATCH: 'pi-users',
  FOLLOW_UP_DUE: 'pi-phone',
  LEAD_IDLE: 'pi-hourglass',
  CONSIGNOR_SETTLEMENT: 'pi-send',
  SUPPLIER_PAYABLE: 'pi-wrench',
  CASH_NEGATIVE: 'pi-wallet',
  PARTNER_OVERDRAWN: 'pi-briefcase',
};

/**
 * The dashboard (SPEC §4.12 #1, §4.17): the "Needs Attention" panel first, then
 * money and stock tiles, installments due, and the partner equity matrix. Every
 * block comes from the API only for users allowed to see it.
 */
@Component({
  selector: 'app-dashboard-page',
  imports: [TranslocoPipe, CardModule, TagModule, RouterLink, MoneyPipe],
  template: `
    <h1 class="page-title" data-testid="dashboard-title">{{ 'dashboard.welcome' | transloco: { name: tenantName() } }}</h1>

    @if (data(); as d) {
      <section class="card attention" data-testid="needs-attention">
        <h2><i class="pi pi-bell" aria-hidden="true"></i> {{ 'attention.title' | transloco }}
          <span class="count">{{ d.attention?.length ?? 0 }}</span></h2>
        <ul>
          @for (item of d.attention ?? []; track $index) {
            <li [class]="item.severity" [attr.data-testid]="'attention-' + item.kind">
              <i class="pi" [class]="icon(item)" aria-hidden="true"></i>
              <a [routerLink]="['/t', context.activeTenantId(), ...item.link]">
                {{ 'attention.' + item.kind | transloco: display(item) }}</a>
            </li>
          } @empty {
            <li class="info">{{ 'attention.none' | transloco }}</li>
          }
        </ul>
      </section>

      <div class="tiles" data-testid="kpi-tiles">
        @if (d.kpis.cash_total !== null && d.kpis.cash_total !== undefined) {
          <div class="tile"><span>{{ 'dashboard.cash' | transloco }}</span><strong data-testid="kpi-cash">{{ d.kpis.cash_total | money }}</strong></div>
          <div class="tile"><span>{{ 'dashboard.bank' | transloco }}</span><strong>{{ d.kpis.bank_total | money }}</strong></div>
        }
        <div class="tile"><span>{{ 'dashboard.stock' | transloco }}</span>
          <strong data-testid="kpi-stock">{{ d.kpis.stock_count }}</strong>
          @if (d.kpis.stock_cost) { <small>{{ 'dashboard.tiedUp' | transloco }} {{ d.kpis.stock_cost | money }}</small> }</div>
        <div class="tile" [class.warn]="d.kpis.aged_count > 0"><span>{{ 'dashboard.aged' | transloco: { days: d.kpis.aged_days } }}</span>
          <strong data-testid="kpi-aged">{{ d.kpis.aged_count }}</strong></div>
        <div class="tile"><span>{{ 'dashboard.monthSales' | transloco }}</span>
          <strong>{{ d.kpis.month_sales_count }}</strong>
          @if (d.kpis.month_gross_profit) {
            <small>{{ 'dashboard.monthProfit' | transloco }} {{ d.kpis.month_gross_profit | money }}</small>
          }</div>
      </div>

      @if (d.installments; as k) {
        <p-card data-testid="installment-tiles">
          <div class="kv"><strong>{{ 'installments.title' | transloco }}</strong>
            <a [routerLink]="['/t', context.activeTenantId(), 'installments']">{{ 'dashboard.open' | transloco }}</a></div>
          <div class="kv"><span>{{ 'installments.due48h' | transloco: { n: k.due_48h_count } }}</span><span>{{ k.due_48h | money }}</span></div>
          <div class="kv"><span>{{ 'installments.due7d' | transloco: { n: k.due_7d_count } }}</span><span>{{ k.due_7d | money }}</span></div>
          <div class="kv"><span>{{ 'installments.overdueN' | transloco: { n: k.overdue_count } }}</span>
            <strong [class.negative]="k.overdue_count > 0" data-testid="dashboard-overdue">{{ k.overdue | money }}</strong></div>
          @if (k.bounced_count > 0) {
            <div class="kv negative"><span>{{ 'installments.bouncedCheques' | transloco }}</span><strong>{{ k.bounced_count }}</strong></div>
          }
        </p-card>
      }

      @if (d.equity?.length) {
        <section class="card" data-testid="equity-matrix">
          <h2>{{ 'dashboard.equity' | transloco }}</h2>
          <div class="scroll-x">
          <table class="equity">
            <thead><tr>
              <th>{{ 'partners.partner' | transloco }}</th><th class="num">%</th>
              <th class="num">{{ 'partners.capital' | transloco }}</th>
              <th class="num">{{ 'dashboard.allocated' | transloco }}</th>
              <th class="num">{{ 'dashboard.drawings' | transloco }}</th>
              <th class="num">{{ 'partners.net' | transloco }}</th>
              <th class="bar-col"></th>
            </tr></thead>
            <tbody>
              @for (row of d.equity; track row.partner_id) {
                <tr>
                  <td><a [routerLink]="['/t', context.activeTenantId(), 'partners', row.partner_id]">{{ partnerName(row) }}</a></td>
                  <td class="num">{{ pct(row.percentage) }}</td>
                  <td class="num">{{ row.capital | money }}</td>
                  <td class="num">{{ row.allocated_profit | money }}</td>
                  <td class="num">{{ row.drawings | money }}</td>
                  <td class="num strong" [class.negative]="row.net.startsWith('-')">{{ row.net | money }}</td>
                  <td class="bar-col"><span class="bar" [style.inline-size.%]="barWidth(row)"></span></td>
                </tr>
              }
            </tbody>
          </table>
          </div>
        </section>
      }
    }

    @if (myPosition(); as s) {
      <p-card data-testid="my-position">
        <div class="kv"><strong>{{ 'dashboard.myPosition' | transloco }}</strong></div>
        <div class="kv"><span>{{ 'partners.capital' | transloco }}</span><span>{{ s.closing.capital | money }}</span></div>
        <div class="kv"><span>{{ 'partners.current' | transloco }}</span><span>{{ s.closing.current | money }}</span></div>
        <div class="kv"><span>{{ 'partners.net' | transloco }}</span><strong>{{ s.closing.net | money }}</strong></div>
        <a [routerLink]="['/t', context.activeTenantId(), 'partners', s.partner.id]">{{ 'dashboard.openStatement' | transloco }}</a>
      </p-card>
    }

    <p class="role sub">
      {{ 'dashboard.yourRole' | transloco }}:
      <p-tag data-testid="role" [value]="'roles.' + (context.active()?.role_code ?? '') | transloco" />
      · {{ 'subscription.' + (context.active()?.subscription_status ?? '') | transloco }}
    </p>
  `,
  styles: `
    :host {
      display: grid;
      gap: var(--space-3);
    }
    .attention {
      h2 {
        display: flex;
        gap: var(--space-2);
        align-items: center;
        margin: 0 0 var(--space-2);
      }
      .count {
        padding: 0 var(--space-2);
        font-size: 0.85rem;
        background: var(--color-border);
        border-radius: 999px;
      }
      ul {
        display: grid;
        gap: var(--space-1);
        padding: 0;
        margin: 0;
        list-style: none;
      }
      li {
        display: flex;
        gap: var(--space-2);
        align-items: baseline;
        padding: var(--space-1) var(--space-2);
        border-inline-start: 4px solid #94a3b8;
        border-radius: 4px;
      }
      li.danger {
        background: #fef2f2;
        border-color: #dc2626;
      }
      li.warn {
        background: #fffbeb;
        border-color: #d97706;
      }
      li.info {
        background: #f8fafc;
      }
    }
    .tiles {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(170px, 100%), 1fr));
      gap: var(--space-2);
    }
    .tile {
      display: grid;
      gap: var(--space-1);
      padding: var(--space-3);
      background: var(--color-surface, #fff);
      border: 1px solid var(--color-border);
      border-radius: 8px;

      span,
      small {
        color: var(--color-text-muted);
      }
      strong {
        font-size: 1.25rem;
      }
    }
    .tile.warn strong {
      color: #b45309;
    }
    .kv {
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-block-size: 40px;
    }
    .negative {
      color: var(--color-danger);
    }
    .scroll-x {
      overflow-x: auto;
    }
    section,
    p-card {
      min-inline-size: 0;
    }
    .equity {
      width: 100%;
      border-collapse: collapse;

      th,
      td {
        padding: var(--space-1) var(--space-2);
        text-align: start;
        border-block-end: 1px solid var(--color-border);
      }
      .num {
        text-align: end;
        white-space: nowrap;
      }
      .bar-col {
        inline-size: 25%;
      }
      .bar {
        display: block;
        block-size: 10px;
        background: var(--p-primary-color, #1d4ed8);
        border-radius: 5px;
      }
    }
    @media (width < 720px) {
      .equity .bar-col,
      .equity th:nth-child(4),
      .equity td:nth-child(4),
      .equity th:nth-child(5),
      .equity td:nth-child(5) {
        display: none;
      }
    }
  `,
})
export class DashboardPage implements OnInit {
  protected readonly context = inject(TenantContextService);
  private readonly language = inject(LanguageService);
  private readonly partners = inject(PartnersService);
  private readonly format = inject(FormatService);
  private readonly reports = inject(ReportsService);

  protected readonly data = signal<Dashboard | null>(null);
  /** A partner sees their own position at a glance (SPEC §1.2). */
  protected readonly myPosition = signal<PartnerStatement | null>(null);

  ngOnInit(): void {
    if (this.context.can('dashboard.view')) {
      void this.reports
        .dashboard()
        .then((d) => this.data.set(d))
        .catch(() => this.data.set(null));
    }
    const partnerId = this.context.active()?.partner_id;
    if (partnerId && (this.context.can('partner.view_own') || this.context.can('partner.view_all'))) {
      const today = this.format.todayIso();
      void this.partners
        .statement(partnerId, today, today)
        .then((s) => this.myPosition.set(s))
        .catch(() => this.myPosition.set(null));
    }
  }

  protected icon(item: AttentionItem): string {
    return ICONS[item.kind] ?? 'pi-info-circle';
  }

  /** Message parameters: amounts formatted, dates shown the tenant's way. */
  protected display(item: AttentionItem): Record<string, unknown> {
    const out: Record<string, unknown> = { ...item.params };
    for (const key of ['amount', 'profit']) {
      if (typeof out[key] === 'string') {
        out[key] = this.format.money(out[key] as string);
      }
    }
    for (const key of ['due_date', 'date']) {
      if (typeof out[key] === 'string') {
        out[key] = this.format.date(out[key] as string);
      }
    }
    if (this.language.language() === 'en' && item.params['account_en']) {
      out['account'] = item.params['account_en'];
    }
    return out;
  }

  protected partnerName(row: EquityRow): string {
    return this.language.language() === 'en' && row.name_en ? row.name_en : row.name_ar;
  }

  protected pct(value: string): string {
    return `${Number(value).toFixed(2)}%`;
  }

  protected barWidth(row: EquityRow): number {
    const max = Math.max(...(this.data()?.equity ?? []).map((r) => Math.abs(Number(r.net))), 1);
    return Math.max(0, (Number(row.net) / max) * 100);
  }

  protected readonly tenantName = computed(() => {
    const active = this.context.active();
    return this.language.language() === 'en' && active?.tenant_name_en ? active.tenant_name_en : (active?.tenant_name_ar ?? '');
  });
}
