import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';

import { Invoice, PlatformTenant, SupportSummary } from '../../core/api/api.models';
import { AppDatePipe, FormatService, MoneyPipe } from '../../core/format/format.service';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { PlatformService } from './platform.service';

type Status = 'TRIAL' | 'ACTIVE' | 'PAST_DUE' | 'SUSPENDED';

/**
 * Super admin console (SPEC §4.16): every showroom with plan, status and usage;
 * status and plan changes with a reason; manual invoices; support view only
 * inside a window the showroom granted.
 */
@Component({
  selector: 'app-admin-page',
  imports: [FormsModule, RouterLink, TranslocoPipe, ButtonModule, InputTextModule, MessageModule, TableModule, TagModule,
            MoneyPipe, AppDatePipe, StateComponent],
  template: `
    <main class="admin">
      <a class="back" routerLink="/tenants">← {{ 'tenants.title' | transloco }}</a>
      <h1 class="page-title">{{ 'admin.title' | transloco }}</h1>
      @if (!allowed()) {
        <app-state kind="error" [message]="'errors.PERMISSION_DENIED' | transloco" />
      } @else {
        <p-table [value]="tenants()" styleClass="p-datatable-sm" data-testid="admin-tenants">
          <ng-template #header>
            <tr>
              <th>{{ 'admin.showroom' | transloco }}</th><th>{{ 'admin.plan' | transloco }}</th>
              <th>{{ 'admin.status' | transloco }}</th><th class="num">{{ 'admin.users' | transloco }}</th>
              <th class="num">{{ 'admin.stock' | transloco }}</th><th class="num">{{ 'admin.lines' | transloco }}</th>
              <th>{{ 'admin.lastActivity' | transloco }}</th><th></th>
            </tr>
          </ng-template>
          <ng-template #body let-t>
            <tr [class.selected]="t.id === selected()?.id" [attr.data-testid]="'admin-row-' + t.id">
              <td>{{ t.name_ar }}<div class="sub">{{ t.country_code }} · {{ t.created_at | appDate }}</div></td>
              <td>{{ t.plan_code }}</td>
              <td><p-tag [value]="t.subscription_status" [severity]="severity(t.subscription_status)" />
                @if (t.support_granted) { <p-tag severity="info" [value]="'admin.supportOpen' | transloco" /> }</td>
              <td class="num">{{ t.users }}</td>
              <td class="num">{{ t.vehicles_in_stock }}</td>
              <td class="num">{{ t.journal_lines }}</td>
              <td>{{ t.last_activity ? (t.last_activity | appDate) : '—' }}</td>
              <td><p-button [text]="true" size="small" [label]="'admin.manage' | transloco" (onClick)="select(t)"
                            [attr.data-testid]="'admin-manage-' + t.id" /></td>
            </tr>
          </ng-template>
        </p-table>

        @if (selected(); as t) {
          <section class="card" data-testid="admin-panel">
            <h2>{{ t.name_ar }}</h2>
            <div class="row">
              <label>{{ 'admin.status' | transloco }}
                <select [(ngModel)]="status" data-testid="admin-status">
                  @for (s of statuses; track s) { <option [value]="s">{{ s }}</option> }
                </select></label>
              <label>{{ 'admin.plan' | transloco }}
                <select [(ngModel)]="plan">
                  <option value="TRIAL">TRIAL</option><option value="STANDARD">STANDARD</option>
                </select></label>
              <input pInputText [(ngModel)]="reason" [placeholder]="'vehicles.reason' | transloco"
                     [attr.aria-label]="'vehicles.reason' | transloco" data-testid="admin-reason" />
              <p-button [label]="'settings.save' | transloco" (onClick)="save(t)" [disabled]="reason.trim().length < 3"
                        data-testid="admin-save" />
            </div>

            <h3>{{ 'admin.invoices' | transloco }}</h3>
            <ul class="list">
              @for (i of invoices(); track i.id) {
                <li>{{ i.period_start | appDate }} — {{ i.period_end | appDate }} · {{ i.amount | money: i.currency_code }}
                  <p-tag [value]="i.status" [severity]="i.status === 'PAID' ? 'success' : 'warn'" />
                  @if (i.status === 'ISSUED') {
                    <p-button [text]="true" size="small" [label]="'admin.markPaid' | transloco" (onClick)="paid(t, i)" />
                  }
                </li>
              } @empty { <li class="sub">—</li> }
            </ul>
            <div class="row">
              <input pInputText type="date" [(ngModel)]="periodStart" [attr.aria-label]="'reports.from' | transloco" />
              <input pInputText type="date" [(ngModel)]="periodEnd" [attr.aria-label]="'reports.to' | transloco" />
              <input pInputText [(ngModel)]="amount" inputmode="decimal" dir="ltr" [attr.aria-label]="'finance.amount' | transloco" />
              <p-button [outlined]="true" [label]="'admin.issue' | transloco" (onClick)="issue(t)" [disabled]="!amount" />
            </div>

            <h3>{{ 'admin.support' | transloco }}</h3>
            <p-button [outlined]="true" icon="pi pi-eye" [label]="'admin.supportView' | transloco" (onClick)="support(t)"
                      data-testid="admin-support" />
            @if (summary(); as s) {
              <div class="summary" data-testid="admin-summary">
                <p class="sub">{{ 'admin.grantedUntil' | transloco }} {{ s.granted_until | appDate }}</p>
                <p>@for (c of entries(s.counts); track c[0]) { <span class="chip">{{ c[0] }}: {{ c[1] }}</span> }</p>
                <p>@for (c of entries(s.vehicles_by_status); track c[0]) { <span class="chip">{{ c[0] }}: {{ c[1] }}</span> }</p>
              </div>
            }
          </section>
        }
        @if (error()) { <p-message severity="error" data-testid="admin-error">{{ error() }}</p-message> }
      }
    </main>
  `,
  styles: `
    .admin {
      max-inline-size: 1200px;
      padding: var(--space-4);
      margin-inline: auto;
    }
    .row {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      align-items: center;
      margin-block: var(--space-2);
    }
    .list {
      padding: 0;
      list-style: none;
    }
    .chip {
      display: inline-block;
      padding: 2px var(--space-2);
      margin: 2px;
      background: var(--color-border);
      border-radius: 999px;
    }
    tr.selected td {
      background: #eff6ff;
    }
  `,
})
export class AdminPage implements OnInit {
  private readonly api = inject(PlatformService);
  private readonly context = inject(TenantContextService);
  private readonly errors = inject(ErrorMessageService);
  private readonly format = inject(FormatService);

  protected readonly allowed = signal(true);
  protected readonly tenants = signal<PlatformTenant[]>([]);
  protected readonly selected = signal<PlatformTenant | null>(null);
  protected readonly invoices = signal<Invoice[]>([]);
  protected readonly summary = signal<SupportSummary | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly statuses: Status[] = ['TRIAL', 'ACTIVE', 'PAST_DUE', 'SUSPENDED'];
  protected status: Status = 'ACTIVE';
  protected plan: 'TRIAL' | 'STANDARD' = 'TRIAL';
  protected reason = '';
  protected periodStart = '';
  protected periodEnd = '';
  protected amount = '';

  async ngOnInit(): Promise<void> {
    const me = await this.context.ensureLoaded();
    this.allowed.set(me.is_platform_admin);
    if (me.is_platform_admin) {
      await this.load();
    }
  }

  private async load(): Promise<void> {
    await this.run(async () => this.tenants.set(await this.api.tenants()));
  }

  protected entries(record: Record<string, number>): [string, number][] {
    return Object.entries(record);
  }

  protected severity(status: string | null): 'success' | 'info' | 'warn' | 'danger' | 'secondary' {
    return status === 'ACTIVE' ? 'success' : status === 'TRIAL' ? 'info' : status === 'PAST_DUE' ? 'warn' : 'danger';
  }

  protected async select(tenant: PlatformTenant): Promise<void> {
    this.selected.set(tenant);
    this.summary.set(null);
    this.status = (tenant.subscription_status ?? 'ACTIVE') as Status;
    this.plan = (tenant.plan_code ?? 'TRIAL') as 'TRIAL' | 'STANDARD';
    this.reason = '';
    const today = this.format.todayIso();
    this.periodStart = `${today.slice(0, 8)}01`;
    this.periodEnd = today;
    await this.run(async () => this.invoices.set(await this.api.invoices(tenant.id)));
  }

  protected async save(tenant: PlatformTenant): Promise<void> {
    await this.run(async () => {
      const updated = await this.api.updateTenant(tenant.id, {
        subscription_status: this.status,
        plan_code: this.plan,
        reason: this.reason.trim(),
      });
      this.selected.set(updated);
      await this.load();
    });
  }

  protected async issue(tenant: PlatformTenant): Promise<void> {
    await this.run(async () => {
      await this.api.issueInvoice(tenant.id, { period_start: this.periodStart, period_end: this.periodEnd, amount: this.amount });
      this.amount = '';
      this.invoices.set(await this.api.invoices(tenant.id));
    });
  }

  protected async paid(tenant: PlatformTenant, invoice: Invoice): Promise<void> {
    await this.run(async () => {
      await this.api.markPaid(tenant.id, invoice.id, null);
      this.invoices.set(await this.api.invoices(tenant.id));
      await this.load();
    });
  }

  protected async support(tenant: PlatformTenant): Promise<void> {
    await this.run(async () => this.summary.set(await this.api.support(tenant.id)));
  }

  private async run(action: () => Promise<void>): Promise<void> {
    this.error.set(null);
    try {
      await action();
    } catch (error) {
      this.error.set(this.errors.message(error));
    }
  }
}
