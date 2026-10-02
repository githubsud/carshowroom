import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';

import {
  CashAccount,
  CashBook,
  ExpenseCategory,
  ExpensePosting,
  OtherIncomePosting,
  Partner,
  GeneralExpense,
  PostingWarning,
  Transfer,
  TransferPosting,
} from '../../core/api/api.models';
import { AppDatePipe, FormatService, MoneyPipe } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { translationsLoaded } from '../../shared/translated';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { PartnersService } from '../partners/partners.service';
import { ExpenseDialogComponent } from './expense-dialog.component';
import { FinanceService } from './finance.service';
import { IncomeDialogComponent } from './income-dialog.component';
import { TransferDialogComponent } from './transfer-dialog.component';

type View = 'book' | 'expenses' | 'transfers';

/** Cash & bank (SPEC §4.10, screen 11): balances, cash book, expenses, transfers. */
@Component({
  selector: 'app-cash-page',
  imports: [
    FormsModule,
    TranslocoPipe,
    ButtonModule,
    InputTextModule,
    SelectButtonModule,
    TableModule,
    TagModule,
    StateComponent,
    MoneyPipe,
    AppDatePipe,
    CanDirective,
    ExpenseDialogComponent,
    TransferDialogComponent,
    IncomeDialogComponent,
  ],
  templateUrl: './cash.page.html',
  styleUrl: './cash.page.scss',
})
export class CashPage implements OnInit {
  private readonly finance = inject(FinanceService);
  private readonly partnersApi = inject(PartnersService);
  private readonly context = inject(TenantContextService);
  private readonly format = inject(FormatService);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  private readonly translations = translationsLoaded();
  protected readonly language = inject(LanguageService);

  protected readonly state = signal<'loading' | 'ready' | 'error'>('loading');
  protected readonly loadError = signal<string | null>(null);
  protected readonly accounts = signal<CashAccount[]>([]);
  protected readonly categories = signal<ExpenseCategory[]>([]);
  protected readonly partners = signal<Partner[]>([]);
  protected readonly selectedId = signal<string | null>(null);
  protected readonly selected = computed(() => this.accounts().find((a) => a.id === this.selectedId()) ?? null);

  protected readonly view = signal<View>('book');
  protected readonly viewOptions = computed(() => {
    this.translations(); // re-translate once loaded and on language change
    return (['book', 'expenses', 'transfers'] as const).map((value) => ({
      value,
      label: this.transloco.translate(`finance.view_${value}`),
    }));
  });

  protected dateFrom = '';
  protected dateTo = '';
  protected readonly book = signal<CashBook | null>(null);
  protected readonly bookLoading = signal(false);
  protected readonly expenses = signal<GeneralExpense[]>([]);
  protected readonly transfers = signal<Transfer[]>([]);
  protected readonly downloading = signal<'xlsx' | 'pdf' | null>(null);

  protected readonly expenseOpen = signal(false);
  protected readonly transferOpen = signal(false);
  protected readonly incomeOpen = signal(false);

  ngOnInit(): void {
    const today = this.format.todayIso();
    this.dateFrom = `${today.slice(0, 8)}01`;
    this.dateTo = today;
    void this.load();
  }

  protected async load(): Promise<void> {
    this.state.set('loading');
    try {
      const [accounts, categories, partners] = await Promise.all([
        this.finance.cashAccounts(),
        this.finance.categories('GENERAL'),
        // Partners for "paid personally by a partner" (rule 30), only for those allowed to see them.
        this.context.can('partner.view_all') ? this.partnersApi.list() : Promise.resolve([]),
      ]);
      this.accounts.set(accounts);
      this.categories.set(categories);
      this.partners.set(partners);
      if (!this.selected()) {
        this.selectedId.set(accounts.find((a) => a.is_default)?.id ?? accounts[0]?.id ?? null);
      }
      this.state.set('ready');
      await this.refreshView();
    } catch (error) {
      this.loadError.set(this.errors.message(error));
      this.state.set('error');
    }
  }

  protected name(item: { name_ar: string; name_en?: string | null }): string {
    return this.language.language() === 'ar' ? item.name_ar : (item.name_en ?? item.name_ar);
  }

  protected select(account: CashAccount): void {
    this.selectedId.set(account.id);
    this.view.set('book');
    void this.refreshView();
  }

  protected setView(view: View): void {
    this.view.set(view);
    void this.refreshView();
  }

  protected async refreshView(): Promise<void> {
    const account = this.selected();
    this.bookLoading.set(true);
    try {
      if (this.view() === 'book' && account && this.dateFrom && this.dateTo) {
        this.book.set(await this.finance.cashBook(account.id, this.dateFrom, this.dateTo));
      } else if (this.view() === 'expenses') {
        this.expenses.set((await this.finance.expenses({ date_from: this.dateFrom, date_to: this.dateTo, page_size: 200 })).items);
      } else if (this.view() === 'transfers') {
        this.transfers.set((await this.finance.transfers({ date_from: this.dateFrom, date_to: this.dateTo, page_size: 200 })).items);
      }
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    } finally {
      this.bookLoading.set(false);
    }
  }

  protected async download(format: 'xlsx' | 'pdf'): Promise<void> {
    const account = this.selected();
    if (!account) {
      return;
    }
    this.downloading.set(format);
    try {
      await this.finance.downloadCashBook(account.id, this.dateFrom, this.dateTo, format, this.language.language());
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    } finally {
      this.downloading.set(null);
    }
  }

  protected async onPosted(result: ExpensePosting | TransferPosting | OtherIncomePosting): Promise<void> {
    const entryNo = result.journal_entries[0]?.entry_no;
    this.toast.add({
      severity: 'success',
      summary: this.transloco.translate('finance.posted', { entryNo }),
    });
    for (const warning of result.warnings ?? []) {
      this.toast.add({ severity: 'warn', summary: this.warningText(warning) });
    }
    await this.load();
  }

  private warningText(warning: PostingWarning): string {
    const details = warning.details ?? {};
    return this.transloco.translate(`warnings.${warning.code}`, {
      name: this.language.language() === 'ar' ? details['name_ar'] : details['name_en'],
      balanceAfter: details['balance_after'],
    });
  }
}
