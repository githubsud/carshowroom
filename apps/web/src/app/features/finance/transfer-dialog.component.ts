import { Component, computed, effect, inject, input, model, output, signal } from '@angular/core';
import { AbstractControl, NonNullableFormBuilder, ReactiveFormsModule, ValidationErrors, Validators } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectModule } from 'primeng/select';

import { CashAccount, Preview, TransferPosting } from '../../core/api/api.models';
import { FormatService } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { PostingPreviewComponent } from '../../shared/components/posting-preview.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { positiveMoney } from '../../shared/money-input';
import { FinanceService } from './finance.service';

function differentAccounts(group: AbstractControl): ValidationErrors | null {
  const from = group.get('from_cash_account_id')?.value;
  const to = group.get('to_cash_account_id')?.value;
  return from && to && from === to ? { sameAccount: true } : null;
}

/** Move money between a cash box and a bank account (rule 21). */
@Component({
  selector: 'app-transfer-dialog',
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
export class TransferDialogComponent {
  private readonly finance = inject(FinanceService);
  private readonly format = inject(FormatService);
  private readonly errors = inject(ErrorMessageService);
  protected readonly language = inject(LanguageService);

  readonly visible = model(false);
  readonly accounts = input.required<CashAccount[]>();
  readonly posted = output<TransferPosting>();

  protected readonly kind: 'expense' | 'transfer' = 'transfer';
  protected readonly step = signal<'form' | 'preview'>('form');
  protected readonly preview = signal<Preview | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  private idempotencyKey = crypto.randomUUID();

  protected readonly form = inject(NonNullableFormBuilder).group(
    {
      transfer_date: ['', Validators.required],
      from_cash_account_id: ['', Validators.required],
      to_cash_account_id: ['', Validators.required],
      amount: ['', [Validators.required, positiveMoney]],
      notes: [''],
    },
    { validators: differentAccounts },
  );

  protected readonly accountOptions = computed(() =>
    this.accounts().map((a) => ({
      value: a.id,
      label: this.language.language() === 'ar' ? a.name_ar : (a.name_en ?? a.name_ar),
    })),
  );
  // Unused by this dialog; the shared template checks for it.
  protected readonly categoryOptions = computed(() => [] as { value: string; label: string }[]);

  constructor() {
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
    const cashBox = this.accounts().find((a) => a.kind === 'CASH_BOX');
    const bank = this.accounts().find((a) => a.kind === 'BANK');
    this.form.reset({
      transfer_date: this.format.todayIso(),
      from_cash_account_id: cashBox?.id ?? '',
      to_cash_account_id: bank?.id ?? '',
      amount: '',
      notes: '',
    });
  }

  private body() {
    const value = this.form.getRawValue();
    return { ...value, notes: value.notes.trim() || null };
  }

  protected async review(): Promise<void> {
    if (this.form.invalid || this.busy()) {
      this.form.markAllAsTouched();
      return;
    }
    await this.run(async () => {
      this.preview.set(await this.finance.previewTransfer(this.body()));
      this.step.set('preview');
    });
  }

  protected async confirm(): Promise<void> {
    await this.run(async () => {
      const result = await this.finance.recordTransfer(this.body(), this.idempotencyKey);
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
