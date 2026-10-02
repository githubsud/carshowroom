import { Component, computed, inject, input, output } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { CheckboxModule } from 'primeng/checkbox';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';

import { PlanPosting, Preview, ReceiptInput } from '../../core/api/api.models';
import { MoneyPipe } from '../../core/format/format.service';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { PostingShellComponent } from '../../shared/components/posting-shell.component';
import { positiveMoney } from '../../shared/money-input';
import { PostingDialogBase, PostingKind } from '../finance/posting-dialog.base';
import { InstallmentsService } from './installments.service';

/**
 * Collect an installment payment (rule 15): allocated oldest first; partial
 * payments are fine. More than what is owed is refused, unless the showroom
 * keeps overpayments as customer credit (D-41) and the user ticks it.
 */
@Component({
  selector: 'app-receipt-dialog',
  imports: [ReactiveFormsModule, TranslocoPipe, CheckboxModule, InputTextModule, SelectModule, MoneyInputComponent, MoneyPipe, PostingShellComponent],
  template: `
    <app-posting-shell [visible]="visible()" [header]="'installments.collectTitle' | transloco" [form]="form"
                       [step]="step()" [preview]="preview()" [error]="error()" [busy]="busy()" testId="receipt-form"
                       (review)="review()" (confirm)="confirm()" (back)="back()" (dismiss)="visible.set(false)">
      <div class="dialog-fields" [formGroup]="form">
        <p class="owed">{{ 'installments.stillOwed' | transloco }}: <strong>{{ owed() | money }}</strong></p>
        <div class="field">
          <label for="r-amount">{{ 'finance.amount' | transloco }}</label>
          <app-money-input inputId="r-amount" formControlName="amount" data-testid="amount" />
        </div>
        <div class="field">
          <label for="r-cash">{{ 'finance.receivedIn' | transloco }}</label>
          <p-select inputId="r-cash" formControlName="cash_account_id" [options]="accountOptions()" optionLabel="label"
                    optionValue="value" [fluid]="true" />
        </div>
        <div class="field">
          <label for="r-date">{{ 'finance.date' | transloco }}</label>
          <input pInputText id="r-date" type="date" formControlName="receipt_date" />
        </div>
        @if (creditAllowed()) {
          <div class="check">
            <p-checkbox formControlName="keep_excess_as_credit" [binary]="true" inputId="r-credit" />
            <label for="r-credit">{{ 'installments.keepExcess' | transloco }}</label>
          </div>
        }
      </div>
    </app-posting-shell>
  `,
  styles: `
    .owed {
      margin: 0;
    }
    .check {
      display: flex;
      gap: var(--space-2);
      align-items: center;
    }
  `,
})
export class ReceiptDialogComponent extends PostingDialogBase<ReceiptInput, PlanPosting> {
  private readonly api = inject(InstallmentsService);
  private readonly context = inject(TenantContextService);

  readonly planId = input.required<string>();
  readonly owed = input.required<string>();
  /** Pre-filled amount, e.g. the next installment. */
  readonly suggested = input<string>('');
  readonly posted = output<PlanPosting>();

  readonly kind: PostingKind = 'receipt';
  readonly dateControl = 'receipt_date';
  readonly noteControl = 'notes';
  readonly form = inject(NonNullableFormBuilder).group({
    amount: ['', [Validators.required, positiveMoney]],
    cash_account_id: ['', Validators.required],
    receipt_date: ['', Validators.required],
    keep_excess_as_credit: [false],
    notes: [''],
  });
  protected readonly creditAllowed = computed(
    () => this.context.tenant()?.settings.overpayment_policy === 'ALLOW_AS_CREDIT',
  );

  protected reset(): void {
    this.form.reset({
      amount: this.suggested() || this.owed(),
      cash_account_id: this.defaultAccountId(),
      receipt_date: this.format.todayIso(),
      keep_excess_as_credit: false,
      notes: '',
    });
  }

  protected body(): ReceiptInput {
    const v = this.form.getRawValue();
    return {
      receipt_date: v.receipt_date,
      amount: v.amount,
      source: 'CASH_ACCOUNT',
      cash_account_id: v.cash_account_id,
      keep_excess_as_credit: v.keep_excess_as_credit,
      notes: v.notes.trim() || null,
    };
  }

  protected previewCall(body: ReceiptInput): Promise<Preview> {
    return this.api.previewReceipt(this.planId(), body);
  }

  protected postCall(body: ReceiptInput, key: string): Promise<PlanPosting> {
    return this.api.recordReceipt(this.planId(), body, key);
  }

  protected emitPosted(result: PlanPosting): void {
    this.posted.emit(result);
  }
}
