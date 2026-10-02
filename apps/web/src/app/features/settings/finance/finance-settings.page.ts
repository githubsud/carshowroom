import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule, NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';

import { CashAccount, ExpenseCategory } from '../../../core/api/api.models';
import { MoneyPipe } from '../../../core/format/format.service';
import { LanguageService } from '../../../core/i18n/language.service';
import { StateComponent } from '../../../shared/components/state.component';
import { ErrorMessageService } from '../../../shared/error-message.service';
import { FinanceService } from '../../finance/finance.service';

/** Settings → cash boxes, bank accounts and expense categories (SPEC §4.1). */
@Component({
  selector: 'app-finance-settings-page',
  imports: [
    FormsModule,
    ReactiveFormsModule,
    TranslocoPipe,
    ButtonModule,
    DialogModule,
    InputTextModule,
    MessageModule,
    SelectButtonModule,
    TableModule,
    TagModule,
    MoneyPipe,
    StateComponent,
  ],
  templateUrl: './finance-settings.page.html',
  styles: `
    .section-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-block: var(--space-4) var(--space-2);
    }

    h2 {
      margin: 0;
      font-size: 1.15rem;
    }

    .num {
      font-variant-numeric: tabular-nums;
      text-align: end;
    }

    .sub {
      font-size: 0.8125rem;
      color: var(--color-text-muted);
    }

    .actions {
      text-align: end;
    }

    .dialog-form {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }

    .field {
      display: flex;
      flex-direction: column;
      gap: var(--space-1);
    }

    .dialog-actions {
      display: flex;
      gap: var(--space-2);
      justify-content: flex-end;
    }
  `,
})
export class FinanceSettingsPage implements OnInit {
  private readonly finance = inject(FinanceService);
  private readonly toast = inject(MessageService);
  private readonly errors = inject(ErrorMessageService);
  private readonly fb = inject(NonNullableFormBuilder);
  protected readonly language = inject(LanguageService);

  protected readonly state = signal<'loading' | 'ready' | 'error'>('loading');
  protected readonly loadError = signal<string | null>(null);
  protected readonly accounts = signal<CashAccount[]>([]);
  protected readonly categories = signal<ExpenseCategory[]>([]);

  protected readonly accountOpen = signal(false);
  protected readonly categoryOpen = signal(false);
  protected readonly busy = signal(false);
  protected readonly dialogError = signal<string | null>(null);

  protected readonly kindOptions = [
    { value: 'CASH_BOX', key: 'settings.cashBox' },
    { value: 'BANK', key: 'settings.bank' },
  ];
  protected readonly categoryKindOptions = [
    { value: 'GENERAL', key: 'settings.generalCategory' },
    { value: 'VEHICLE', key: 'settings.vehicleCategory' },
  ];

  protected readonly accountForm = this.fb.group({
    kind: ['CASH_BOX' as 'CASH_BOX' | 'BANK', Validators.required],
    name_ar: ['', Validators.required],
    name_en: [''],
    bank_name: [''],
    account_number: [''],
    is_default: [false],
  });

  protected readonly categoryForm = this.fb.group({
    kind: ['GENERAL' as 'GENERAL' | 'VEHICLE', Validators.required],
    name_ar: ['', Validators.required],
    name_en: ['', Validators.required],
  });

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    try {
      const [accounts, categories] = await Promise.all([
        this.finance.cashAccounts(true),
        this.finance.categories(undefined, true),
      ]);
      this.accounts.set(accounts);
      this.categories.set(categories);
      this.state.set('ready');
    } catch (error) {
      this.loadError.set(this.errors.message(error));
      this.state.set('error');
    }
  }

  protected name(item: { name_ar: string; name_en?: string | null }): string {
    return this.language.language() === 'ar' ? item.name_ar : (item.name_en ?? item.name_ar);
  }

  protected openAccount(): void {
    this.accountForm.reset({ kind: 'CASH_BOX', name_ar: '', name_en: '', bank_name: '', account_number: '', is_default: false });
    this.dialogError.set(null);
    this.accountOpen.set(true);
  }

  protected openCategory(): void {
    this.categoryForm.reset({ kind: 'GENERAL', name_ar: '', name_en: '' });
    this.dialogError.set(null);
    this.categoryOpen.set(true);
  }

  protected async saveAccount(): Promise<void> {
    if (this.accountForm.invalid) {
      return;
    }
    const value = this.accountForm.getRawValue();
    await this.run(async () => {
      await this.finance.createCashAccount({
        kind: value.kind,
        name_ar: value.name_ar.trim(),
        name_en: value.name_en.trim() || null,
        bank_name: value.kind === 'BANK' ? value.bank_name.trim() || null : null,
        account_number: value.kind === 'BANK' ? value.account_number.trim() || null : null,
        is_default: value.is_default,
      });
      this.accountOpen.set(false);
    });
  }

  protected async saveCategory(): Promise<void> {
    if (this.categoryForm.invalid) {
      return;
    }
    const value = this.categoryForm.getRawValue();
    await this.run(async () => {
      await this.finance.createCategory({ kind: value.kind, name_ar: value.name_ar.trim(), name_en: value.name_en.trim() });
      this.categoryOpen.set(false);
    });
  }

  protected async toggleAccount(account: CashAccount): Promise<void> {
    await this.inline(() => this.finance.updateCashAccount(account.id, { archived: !account.archived }));
  }

  protected async makeDefault(account: CashAccount): Promise<void> {
    await this.inline(() => this.finance.updateCashAccount(account.id, { is_default: true }));
  }

  protected async toggleCategory(category: ExpenseCategory): Promise<void> {
    await this.inline(() => this.finance.updateCategory(category.id, { archived: !category.archived }));
  }

  private async run(action: () => Promise<void>): Promise<void> {
    this.busy.set(true);
    this.dialogError.set(null);
    try {
      await action();
      await this.load();
    } catch (error) {
      this.dialogError.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }

  private async inline(action: () => Promise<unknown>): Promise<void> {
    try {
      await action();
      await this.load();
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    }
  }
}
