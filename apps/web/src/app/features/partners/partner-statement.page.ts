import { Component, computed, inject, input, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';

import { CashAccount, Partner, PartnerPosition, PartnerPosting, PartnerStatement } from '../../core/api/api.models';
import { AppDatePipe, FormatService, MoneyPipe, PercentPipe } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { FinanceService } from '../finance/finance.service';
import { PartnerTransactionDialogComponent } from './partner-transaction-dialog.component';
import { PartnersService } from './partners.service';

/** Partner statement (كشف حساب شريك, SPEC §4.2): opening, every movement, running balance, closing. */
@Component({
  selector: 'app-partner-statement-page',
  imports: [
    FormsModule,
    RouterLink,
    TranslocoPipe,
    ButtonModule,
    InputTextModule,
    TableModule,
    TagModule,
    MoneyPipe,
    PercentPipe,
    AppDatePipe,
    CanDirective,
    StateComponent,
    PartnerTransactionDialogComponent,
  ],
  templateUrl: './partner-statement.page.html',
  styleUrl: './partners.page.scss',
  styles: `
    .positions {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(150px, 100%), 1fr));
      gap: var(--space-2);
      margin-block-end: var(--space-3);
    }

    .position {
      padding: var(--space-3);
      background: var(--color-surface);
      border: 1px solid var(--color-border);
      border-radius: var(--radius);

      span {
        display: block;
        font-size: 0.8125rem;
        color: var(--color-text-muted);
      }

      strong {
        font-size: 1.15rem;
        font-variant-numeric: tabular-nums;
      }

      &.net {
        border-color: var(--color-primary);
      }
    }

    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      align-items: flex-end;
      margin-block-end: var(--space-3);

      label {
        display: flex;
        flex-direction: column;
        gap: 2px;
        font-size: 0.8125rem;
        color: var(--color-text-muted);
      }
    }

    .exports {
      margin-inline-start: auto;
    }

    .meta {
      margin-block: -8px var(--space-3);
      color: var(--color-text-muted);
    }

    .back {
      color: var(--color-primary-link);
      text-decoration: none;
    }
  `,
})
export class PartnerStatementPage implements OnInit {
  private readonly api = inject(PartnersService);
  private readonly finance = inject(FinanceService);
  private readonly format = inject(FormatService);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  protected readonly context = inject(TenantContextService);
  protected readonly language = inject(LanguageService);

  /** Route parameter (withComponentInputBinding). */
  readonly partnerId = input.required<string>();

  protected readonly statement = signal<PartnerStatement | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly accounts = signal<CashAccount[]>([]);
  protected readonly partner = computed<Partner | null>(() => this.statement()?.partner ?? null);
  protected readonly nationalId = signal<string | null>(null);
  protected readonly downloading = signal<'xlsx' | 'pdf' | null>(null);
  protected readonly txnOpen = signal(false);
  protected dateFrom = '';
  protected dateTo = '';

  ngOnInit(): void {
    const today = this.format.todayIso();
    this.dateFrom = `${today.slice(0, 4)}-01-01`;
    this.dateTo = today;
    void this.load();
    if (this.context.can('partner.transact') && this.context.can('cash.view')) {
      void this.finance.cashAccounts().then((a) => this.accounts.set(a));
    }
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.loadError.set(null);
    try {
      this.statement.set(await this.api.statement(this.partnerId(), this.dateFrom, this.dateTo));
    } catch (error) {
      this.loadError.set(this.errors.message(error));
    } finally {
      this.loading.set(false);
    }
  }

  protected name(p: { name_ar: string; name_en?: string | null }): string {
    return this.language.language() === 'ar' ? p.name_ar : (p.name_en ?? p.name_ar);
  }

  protected cards(position: PartnerPosition): { key: string; value: string; net?: boolean }[] {
    return [
      { key: 'partners.capital', value: position.capital },
      { key: 'partners.current', value: position.current },
      { key: 'partners.loansTo', value: position.loans_to_partner },
      { key: 'partners.loansFrom', value: position.loans_from_partner },
      { key: 'partners.net', value: position.net, net: true },
    ];
  }

  protected negative(value: string): boolean {
    return value.startsWith('-');
  }

  protected async reveal(): Promise<void> {
    try {
      this.nationalId.set(await this.api.revealNationalId(this.partnerId()));
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    }
  }

  protected async download(format: 'xlsx' | 'pdf'): Promise<void> {
    this.downloading.set(format);
    try {
      await this.api.downloadStatement(this.partnerId(), this.dateFrom, this.dateTo, format, this.language.language());
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    } finally {
      this.downloading.set(null);
    }
  }

  protected async onPosted(result: PartnerPosting): Promise<void> {
    this.toast.add({
      severity: 'success',
      summary: this.transloco.translate('finance.posted', { entryNo: result.journal_entries[0]?.entry_no }),
    });
    await this.load();
  }
}
