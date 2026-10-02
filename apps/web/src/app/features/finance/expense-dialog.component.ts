import { Component, computed, inject, input, output } from '@angular/core';
import { FormsModule, NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';

import { ExpenseCategory, ExpensePosting, GeneralExpenseInput, Preview } from '../../core/api/api.models';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { PostingPreviewComponent } from '../../shared/components/posting-preview.component';
import { positiveMoney } from '../../shared/money-input';
import { loaded, translationsLoaded } from '../../shared/translated';
import { FinanceService } from './finance.service';
import { Option, PostingDialogBase, PostingKind } from './posting-dialog.base';

/**
 * Record a general expense: paid from a cash box / bank (rule 20) or
 * personally by a partner (rule 30). Smart defaults keep it to a few taps.
 */
@Component({
  selector: 'app-expense-dialog',
  imports: [
    FormsModule,
    ReactiveFormsModule,
    TranslocoPipe,
    ButtonModule,
    DialogModule,
    InputTextModule,
    MessageModule,
    SelectModule,
    SelectButtonModule,
    MoneyInputComponent,
    PostingPreviewComponent,
  ],
  templateUrl: './posting-dialog.html',
  styleUrl: './posting-dialog.scss',
})
export class ExpenseDialogComponent extends PostingDialogBase<GeneralExpenseInput, ExpensePosting> {
  private readonly finance = inject(FinanceService);
  private readonly transloco = inject(TranslocoService);
  private readonly translations = translationsLoaded();

  readonly categories = input.required<ExpenseCategory[]>();
  readonly posted = output<ExpensePosting>();

  readonly kind: PostingKind = 'expense';
  readonly dateControl = 'expense_date';
  readonly noteControl = 'description';
  readonly form = inject(NonNullableFormBuilder).group({
    expense_date: ['', Validators.required],
    category_id: ['', Validators.required],
    amount: ['', [Validators.required, positiveMoney]],
    cash_account_id: [''],
    paid_by_partner_id: [''],
    partner_funding_mode: ['CURRENT_ACCOUNT' as 'CURRENT_ACCOUNT' | 'LOAN'],
    description: [''],
  });

  protected override readonly categoryOptions = computed<Option[]>(() =>
    this.categories().map((c) => ({ value: c.id, label: this.name(c) })),
  );
  protected override readonly fundingOptions = computed<Option[]>(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    return [
      { value: 'cash', label: this.transloco.translate('finance.fundingCash') },
      { value: 'partner', label: this.transloco.translate('finance.fundingPartner') },
    ];
  });
  protected override readonly modeOptions = computed<Option[]>(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    return [
      { value: 'CURRENT_ACCOUNT', label: this.transloco.translate('finance.modeCurrent') },
      { value: 'LOAN', label: this.transloco.translate('finance.modeLoan') },
    ];
  });

  protected override setFunding(value: 'cash' | 'partner'): void {
    super.setFunding(value);
    const { cash_account_id, paid_by_partner_id } = this.form.controls;
    cash_account_id.setValidators(value === 'cash' ? Validators.required : null);
    paid_by_partner_id.setValidators(value === 'partner' ? Validators.required : null);
    cash_account_id.updateValueAndValidity();
    paid_by_partner_id.updateValueAndValidity();
  }

  protected reset(): void {
    this.form.reset({
      expense_date: this.format.todayIso(),
      category_id: '',
      amount: '',
      cash_account_id: this.defaultAccountId(),
      paid_by_partner_id: '',
      partner_funding_mode: 'CURRENT_ACCOUNT',
      description: '',
    });
    this.setFunding('cash');
  }

  protected body(): GeneralExpenseInput {
    const v = this.form.getRawValue();
    const base = {
      expense_date: v.expense_date,
      category_id: v.category_id,
      amount: v.amount,
      description: v.description.trim() || null,
    };
    return this.funding() === 'partner'
      ? { ...base, paid_by_partner_id: v.paid_by_partner_id, partner_funding_mode: v.partner_funding_mode }
      : { ...base, cash_account_id: v.cash_account_id };
  }

  protected previewCall(body: GeneralExpenseInput): Promise<Preview> {
    return this.finance.previewExpense(body);
  }

  protected postCall(body: GeneralExpenseInput, key: string): Promise<ExpensePosting> {
    return this.finance.recordExpense(body, key);
  }

  protected emitPosted(result: ExpensePosting): void {
    this.posted.emit(result);
  }
}
