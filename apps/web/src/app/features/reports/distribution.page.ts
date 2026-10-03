import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';

import { Distribution, DistributionPlan } from '../../core/api/api.models';
import { AppDatePipe, FormatService, MoneyPipe } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { ReportsService } from './reports.service';

/**
 * Close a period and distribute its profit (SPEC §4.9, rules 22-23): pick the
 * dates, see exactly what each partner gets, confirm. The cash payout is a
 * separate drawing from the partner page.
 */
@Component({
  selector: 'app-distribution-page',
  imports: [
    FormsModule,
    TranslocoPipe,
    ButtonModule,
    DialogModule,
    InputTextModule,
    MessageModule,
    TableModule,
    TagModule,
    MoneyPipe,
    AppDatePipe,
    CanDirective,
    StateComponent,
  ],
  template: `
    <div class="page-header"><h1 class="page-title">{{ 'distribution.title' | transloco }}</h1></div>

    <section class="card" *appCan="'profit.distribute'" data-testid="distribution-form">
      <h2>{{ 'distribution.new' | transloco }}</h2>
      <div class="filters">
        <label>{{ 'reports.from' | transloco }} <input pInputText type="date" [(ngModel)]="periodFrom" data-testid="dist-from" /></label>
        <label>{{ 'reports.to' | transloco }} <input pInputText type="date" [(ngModel)]="periodTo" data-testid="dist-to" /></label>
        <p-button icon="pi pi-eye" [label]="'finance.review' | transloco" (onClick)="preview()" [loading]="busy()"
                  data-testid="dist-preview" />
      </div>
      @if (error()) { <p-message severity="error" data-testid="dist-error">{{ error() }}</p-message> }
      @if (plan(); as p) {
        <p class="summary" data-testid="dist-summary">{{ language.language() === 'ar' ? p.summary_ar : p.summary_en }}</p>
        <div class="figures">
          <div class="figure"><span>{{ 'distribution.revenue' | transloco }}</span><strong>{{ p.revenue | money }}</strong></div>
          <div class="figure"><span>{{ 'distribution.expenses' | transloco }}</span><strong>{{ p.expenses | money }}</strong></div>
          <div class="figure" [class.negative]="p.net_profit.startsWith('-')"><span>{{ 'distribution.net' | transloco }}</span>
            <strong data-testid="dist-net">{{ p.net_profit | money }}</strong></div>
          @if (p.allocated_in_advance !== '0.00') {
            <div class="figure"><span>{{ 'distribution.advance' | transloco }}</span><strong>{{ p.allocated_in_advance | money }}</strong></div>
          }
        </div>
        <p-table [value]="p.lines" styleClass="p-datatable-sm" data-testid="dist-lines">
          <ng-template #header>
            <tr><th>{{ 'partners.partner' | transloco }}</th><th class="num">%</th>
              <th class="num">{{ 'distribution.amount' | transloco }}</th></tr>
          </ng-template>
          <ng-template #body let-line>
            <tr><td>{{ language.language() === 'ar' ? line.partner_name_ar : (line.partner_name_en || line.partner_name_ar) }}</td>
              <td class="num">{{ pct(line.weight_pct) }}</td>
              <td class="num strong">{{ line.amount | money }}</td></tr>
          </ng-template>
        </p-table>
        <div class="actions">
          <p-button [text]="true" [label]="'common.cancel' | transloco" (onClick)="plan.set(null)" />
          <p-button icon="pi pi-check" [label]="'distribution.confirm' | transloco" (onClick)="confirm()" [loading]="busy()"
                    data-testid="dist-confirm" />
        </div>
      }
    </section>

    @if (loadError()) {
      <app-state kind="error" [message]="loadError()" (retry)="load()" />
    } @else {
      <p-table [value]="items()" styleClass="p-datatable-sm" data-testid="distributions">
        <ng-template #header>
          <tr>
            <th>{{ 'distribution.period' | transloco }}</th>
            <th class="num">{{ 'distribution.net' | transloco }}</th>
            <th class="num">{{ 'distribution.distributed' | transloco }}</th>
            <th>{{ 'vehicles.status' | transloco }}</th>
            <th></th>
          </tr>
        </ng-template>
        <ng-template #body let-d>
          <tr [class.muted]="d.status !== 'POSTED'">
            <td>{{ d.period_from | appDate }} — {{ d.period_to | appDate }}
              @if (d.distribution_entry_no) { <div class="sub">#{{ d.closing_entry_no }} · #{{ d.distribution_entry_no }}</div> }</td>
            <td class="num">{{ d.net_profit | money }}</td>
            <td class="num">{{ d.distributed | money }}</td>
            <td><p-tag [severity]="d.status === 'POSTED' ? 'success' : 'secondary'" [value]="'distribution.status_' + d.status | transloco" /></td>
            <td>
              @if (d.id === latestId()) {
                <p-button *appCan="'profit.distribute'" [text]="true" severity="danger" size="small"
                          [label]="'distribution.reverse' | transloco" (onClick)="reversing.set(d)" />
              }
            </td>
          </tr>
        </ng-template>
        <ng-template #emptymessage>
          <tr><td colspan="5"><app-state kind="empty" [message]="'distribution.none' | transloco" /></td></tr>
        </ng-template>
      </p-table>
    }

    <p-dialog [visible]="reversing() !== null" (visibleChange)="!$event && reversing.set(null)" [modal]="true"
              [header]="'distribution.reverse' | transloco" [style]="{ width: 'min(420px, 96vw)' }">
      <div class="dialog-fields">
        <p class="sub">{{ 'distribution.reverseHint' | transloco }}</p>
        <div class="field"><label for="rev-reason">{{ 'vehicles.reason' | transloco }}</label>
          <input pInputText id="rev-reason" [(ngModel)]="reason" /></div>
        <p-button severity="danger" [label]="'distribution.reverse' | transloco" (onClick)="reverse()"
                  [disabled]="reason.trim().length < 3" />
      </div>
    </p-dialog>
  `,
  styles: `
    .filters {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      align-items: center;

      label {
        display: flex;
        gap: var(--space-1);
        align-items: center;
      }
    }
    .summary {
      line-height: 1.7;
    }
    .actions {
      display: flex;
      gap: var(--space-2);
      justify-content: flex-end;
      margin-block-start: var(--space-3);
    }
  `,
})
export class DistributionPage implements OnInit {
  private readonly api = inject(ReportsService);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  private readonly format = inject(FormatService);
  protected readonly language = inject(LanguageService);

  protected readonly items = signal<Distribution[]>([]);
  protected readonly plan = signal<DistributionPlan | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly reversing = signal<Distribution | null>(null);
  protected readonly latestId = computed(() => this.items().find((d) => d.status === 'POSTED')?.id ?? null);
  protected periodFrom = '';
  protected periodTo = '';
  protected reason = '';
  private key = crypto.randomUUID();

  async ngOnInit(): Promise<void> {
    await this.load();
    const today = this.format.todayIso();
    const last = this.items().find((d) => d.status === 'POSTED');
    this.periodFrom = last ? this.dayAfter(last.period_to) : `${today.slice(0, 8)}01`;
    this.periodTo = today;
  }

  protected async load(): Promise<void> {
    try {
      this.items.set(await this.api.distributions());
      this.loadError.set(null);
    } catch (error) {
      this.loadError.set(this.errors.message(error));
    }
  }

  protected pct(value: string): string {
    return `${Number(value).toFixed(2)}%`;
  }

  protected async preview(): Promise<void> {
    await this.run(async () => {
      this.key = crypto.randomUUID();
      this.plan.set(await this.api.previewDistribution({ period_from: this.periodFrom, period_to: this.periodTo, notes: null }));
    });
  }

  protected async confirm(): Promise<void> {
    await this.run(async () => {
      await this.api.postDistribution({ period_from: this.periodFrom, period_to: this.periodTo, notes: null }, this.key);
      this.plan.set(null);
      this.toast.add({ severity: 'success', summary: this.transloco.translate('distribution.posted') });
      await this.load();
      this.periodFrom = this.dayAfter(this.periodTo);
    });
  }

  protected async reverse(): Promise<void> {
    const target = this.reversing();
    if (!target) {
      return;
    }
    try {
      await this.api.reverseDistribution(target.id, this.reason.trim());
      this.reversing.set(null);
      this.reason = '';
      await this.load();
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    }
  }

  private dayAfter(iso: string): string {
    const day = new Date(`${iso}T12:00:00Z`);
    day.setUTCDate(day.getUTCDate() + 1);
    return day.toISOString().slice(0, 10);
  }

  private async run(action: () => Promise<void>): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      await action();
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }
}
