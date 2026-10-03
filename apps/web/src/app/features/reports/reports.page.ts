import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';

import { LedgerAccount, ReportName, ReportTable } from '../../core/api/api.models';
import { FormatService } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { StateComponent } from '../../shared/components/state.component';
import { saveBlob } from '../../shared/download';
import { ErrorMessageService } from '../../shared/error-message.service';
import { ReportTableComponent } from './report-table.component';
import { ReportQuery, ReportsService } from './reports.service';

/** Reports that take a single "as of" date instead of a range. */
const AS_OF: ReportName[] = ['trial-balance', 'balance-check'];
/** Reports that are a current snapshot (no date filter). */
const SNAPSHOT: ReportName[] = ['inventory-aging', 'deferred-papers', 'consignments-in', 'consignments-out'];

/** Reports centre (SPEC §4.12): every report with date filters, on screen, PDF and Excel. */
@Component({
  selector: 'app-reports-page',
  imports: [FormsModule, TranslocoPipe, ButtonModule, InputTextModule, SelectModule, StateComponent, ReportTableComponent],
  template: `
    <div class="page-header"><h1 class="page-title">{{ 'reports.title' | transloco }}</h1></div>
    <nav class="report-list" data-testid="report-list" [attr.aria-label]="'reports.title' | transloco">
      @for (name of names(); track name) {
        <button type="button" class="chip" [class.active]="name === current()" (click)="choose(name)"
                [attr.data-testid]="'report-' + name">{{ 'reports.name_' + name | transloco }}</button>
      }
    </nav>

    @if (current(); as name) {
      <div class="filters">
        @if (asOf()) {
          <label>{{ 'reports.asOf' | transloco }} <input pInputText type="date" [(ngModel)]="query.as_of" /></label>
        } @else if (!snapshot()) {
          <label>{{ 'reports.from' | transloco }} <input pInputText type="date" [(ngModel)]="query.date_from" data-testid="report-from" /></label>
          <label>{{ 'reports.to' | transloco }} <input pInputText type="date" [(ngModel)]="query.date_to" data-testid="report-to" /></label>
        }
        @if (name === 'general-ledger') {
          <p-select [options]="accountOptions()" [(ngModel)]="query.account_id" optionLabel="label" optionValue="value"
                    [filter]="true" [placeholder]="'reports.account' | transloco" [style]="{ minWidth: '260px' }" />
        }
        <p-button icon="pi pi-refresh" [label]="'reports.run' | transloco" (onClick)="run()" data-testid="report-run" />
        <p-button icon="pi pi-file-pdf" [outlined]="true" label="PDF" (onClick)="download('pdf')" [disabled]="!table()" />
        <p-button icon="pi pi-file-excel" [outlined]="true" label="Excel" (onClick)="download('xlsx')" [disabled]="!table()"
                  data-testid="report-xlsx" />
      </div>
      @if (error()) {
        <app-state kind="error" [message]="error()" (retry)="run()" />
      } @else if (loading()) {
        <app-state kind="loading" />
      } @else if (table(); as t) {
        <h2 class="report-title">{{ language.language() === 'ar' ? t.title_ar : t.title_en }}
          <small>{{ language.language() === 'ar' ? t.period_ar : t.period_en }}</small></h2>
        <app-report-table [table]="t" />
      }
    } @else {
      <app-state kind="empty" [message]="'reports.choose' | transloco" />
    }
  `,
  styles: `
    .report-list {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      margin-block-end: var(--space-3);
    }
    .chip {
      padding: var(--space-1) var(--space-3);
      font: inherit;
      cursor: pointer;
      background: transparent;
      border: 1px solid var(--color-border);
      border-radius: 999px;
    }
    .chip.active {
      color: #fff;
      background: var(--p-primary-color, #1d4ed8);
      border-color: transparent;
    }
    .filters {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      align-items: center;
      margin-block-end: var(--space-3);

      label {
        display: flex;
        gap: var(--space-1);
        align-items: center;
      }
    }
    .report-title small {
      margin-inline-start: var(--space-2);
      font-size: 0.85rem;
      font-weight: 400;
      color: var(--color-text-muted);
    }
  `,
})
export class ReportsPage implements OnInit {
  private readonly api = inject(ReportsService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly toast = inject(MessageService);
  private readonly errors = inject(ErrorMessageService);
  private readonly format = inject(FormatService);
  protected readonly language = inject(LanguageService);

  protected readonly names = signal<ReportName[]>([]);
  protected readonly current = signal<ReportName | null>(null);
  protected readonly table = signal<ReportTable | null>(null);
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly accounts = signal<LedgerAccount[]>([]);
  protected readonly asOf = computed(() => AS_OF.includes(this.current() as ReportName));
  protected readonly snapshot = computed(() => SNAPSHOT.includes(this.current() as ReportName));
  protected readonly accountOptions = computed(() =>
    this.accounts()
      .filter((a) => a.is_postable)
      .map((a) => ({ value: a.id, label: `${a.code} ${this.language.language() === 'ar' ? a.name_ar : a.name_en}` })),
  );
  protected query: ReportQuery = {};

  async ngOnInit(): Promise<void> {
    const today = this.format.todayIso();
    this.query = { date_from: `${today.slice(0, 8)}01`, date_to: today, as_of: today, account_id: null };
    try {
      this.names.set(await this.api.available());
    } catch (error) {
      this.error.set(this.errors.message(error));
      return;
    }
    const wanted = this.route.snapshot.queryParamMap.get('r') as ReportName | null;
    if (wanted && this.names().includes(wanted)) {
      await this.choose(wanted);
    }
  }

  protected async choose(name: ReportName): Promise<void> {
    this.current.set(name);
    this.table.set(null);
    void this.router.navigate([], { queryParams: { r: name }, replaceUrl: true });
    if (name === 'general-ledger') {
      if (!this.accounts().length) {
        this.accounts.set(await this.api.ledgerAccounts());
      }
      return;
    }
    await this.run();
  }

  private params(): ReportQuery {
    if (this.asOf()) {
      return { as_of: this.query.as_of };
    }
    if (this.snapshot()) {
      return {};
    }
    return { date_from: this.query.date_from, date_to: this.query.date_to, account_id: this.query.account_id };
  }

  protected async run(): Promise<void> {
    const name = this.current();
    if (!name) {
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    try {
      this.table.set(await this.api.run(name, this.params()));
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.loading.set(false);
    }
  }

  protected async download(format: 'pdf' | 'xlsx'): Promise<void> {
    const name = this.current();
    if (!name) {
      return;
    }
    try {
      saveBlob(await this.api.file(name, this.params(), format, this.language.language()), `${name}.${format}`);
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    }
  }
}
