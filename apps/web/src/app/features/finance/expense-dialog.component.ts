import { Component, computed, effect, inject, input, model, output, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectModule } from 'primeng/select';

import { CashAccount, ExpenseCategory, ExpensePosting, Preview } from '../../core/api/api.models';
import { FormatService } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { PostingPreviewComponent } from '../../shared/components/posting-preview.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { positiveMoney } from '../../shared/money-input';
import { FinanceService } from './finance.service';

/**
 * Record a general expense (rule 20): form → plain-language preview → confirm.
 * Smart defaults (today, default cash box) keep it to a few taps (SPEC §9.3).
 */
@Component({
  selector: 'app-expense-dialog',
  imports: [
    ReactiveFormsModule,
    TranslocoPipe,
    ButtonModule,
    DialogModule,
    InputTextModule,
    MessageModule,
    SelectModule,
    MoneyInputComponent,
    PostingPreviewComponent,
  ],
  templateUrl: './posting-dialog.html',
  styleUrl: './posting-dialog.scss',
})
export class ExpenseDialogComponent {
  private readonly finance = inject(FinanceService);
  private readonly format = inject(FormatService);
  private readonly errors = inject(ErrorMessageService);
  protected readonly language = inject(LanguageService);

  readonly visible = model(false);
  readonly accounts = input.required<CashAccount[]>();
  readonly categories = input.required<ExpenseCategory[]>();
  readonly posted = output<ExpensePosting>();

  protected readonly kind: 'expense' | 'transfer' = 'expense';
  protected readonly step = signal<'form' | 'preview'>('form');
  protected readonly preview = signal<Preview | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  private idempotencyKey = crypto.randomUUID();

  protected readonly form = inject(NonNullableFormBuilder).group({
    expense_date: ['', Validators.required],
    category_id: ['', Validators.required],
    amount: ['', [Validators.required, positiveMoney]],
    cash_account_id: ['', Validators.required],
    description: [''],
  });

  protected readonly categoryOptions = computed(() =>
    this.categories().map((c) => ({ value: c.id, label: this.language.language() === 'ar' ? c.name_ar : c.name_en })),
  );
  protected readonly accountOptions = computed(() =>
    this.accounts().map((a) => ({
      value: a.id,
      label: this.language.language() === 'ar' ? a.name_ar : (a.name_en ?? a.name_ar),
    })),
  );

  constructor() {
    // Each opening is a fresh submission with its own idempotency key and defaults.
    effect(() => {
      if (this.visible()) {
        this.reset();
      }
    });
  }

  private reset(): void {
    this.idempotencyKey = crypto.randomUUID();
    this.step.set('form');
    this.preview.set(null);
    this.error.set(null);
    this.form.reset({
      expense_date: this.format.todayIso(),
      category_id: '',
      amount: '',
      cash_account_id: this.accounts().find((a) => a.is_default)?.id ?? this.accounts()[0]?.id ?? '',
      description: '',
    });
  }

  private body() {
    const value = this.form.getRawValue();
    return { ...value, description: value.description.trim() || null };
  }

  protected async review(): Promise<void> {
    if (this.form.invalid || this.busy()) {
      this.form.markAllAsTouched();
      return;
    }
    await this.run(async () => {
      this.preview.set(await this.finance.previewExpense(this.body()));
      this.step.set('preview');
    });
  }

  protected async confirm(): Promise<void> {
    await this.run(async () => {
      const result = await this.finance.recordExpense(this.body(), this.idempotencyKey);
      this.visible.set(false);
      this.posted.emit(result);
    });
  }

  protected back(): void {
    this.step.set('form');
    this.error.set(null);
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
