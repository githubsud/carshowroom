import { Component, inject, input, output } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';

import { Preview } from '../../core/api/api.models';
import { MoneyPipe } from '../../core/format/format.service';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { PostingShellComponent } from '../../shared/components/posting-shell.component';
import { positiveMoney } from '../../shared/money-input';
import { CustomersService } from '../customers/customers.service';
import { PostingDialogBase, PostingKind } from '../finance/posting-dialog.base';
import { SuppliersService } from '../suppliers/suppliers.service';
import { VehiclesService } from './vehicles.service';

export type PaymentMode = 'sellerPayment' | 'supplierPayment' | 'refund';

interface PaymentBody {
  date: string;
  amount: string;
  cash_account_id: string;
  notes: string | null;
}

/**
 * Money owed paid out: the rest of a car's price to its seller (rule 8), a
 * supplier (rule 32), or a customer's credit (P-02). The amount defaults to
 * what is owed and cannot exceed it (the API checks too).
 */
@Component({
  selector: 'app-payment-dialog',
  imports: [ReactiveFormsModule, TranslocoPipe, InputTextModule, SelectModule, MoneyInputComponent, MoneyPipe, PostingShellComponent],
  template: `
    <app-posting-shell [visible]="visible()" [header]="'payments.' + mode() + 'Title' | transloco" [form]="form"
                       [step]="step()" [preview]="preview()" [error]="error()" [busy]="busy()"
                       [testId]="mode() + '-form'" (review)="review()" (confirm)="confirm()" (back)="back()"
                       (dismiss)="visible.set(false)">
      <div class="dialog-fields" [formGroup]="form">
        <p class="owed">{{ 'payments.owed' | transloco }}: <strong>{{ owed() | money }}</strong></p>
        <div class="field">
          <label for="pay-amount">{{ 'finance.amount' | transloco }}</label>
          <app-money-input inputId="pay-amount" formControlName="amount" data-testid="amount" />
        </div>
        <div class="field">
          <label for="pay-cash">{{ 'finance.paidFrom' | transloco }}</label>
          <p-select inputId="pay-cash" formControlName="cash_account_id" [options]="accountOptions()"
                    optionLabel="label" optionValue="value" [fluid]="true" />
        </div>
        <div class="row">
          <div class="field">
            <label for="pay-date">{{ 'finance.date' | transloco }}</label>
            <input pInputText id="pay-date" type="date" formControlName="date" />
          </div>
          <div class="field">
            <label for="pay-note">{{ 'finance.note' | transloco }}</label>
            <input pInputText id="pay-note" formControlName="notes" />
          </div>
        </div>
      </div>
    </app-posting-shell>
  `,
  styles: `
    .owed {
      margin: 0;
    }
  `,
})
export class PaymentDialogComponent extends PostingDialogBase<PaymentBody, unknown> {
  private readonly vehiclesApi = inject(VehiclesService);
  private readonly suppliersApi = inject(SuppliersService);
  private readonly customersApi = inject(CustomersService);

  readonly mode = input.required<PaymentMode>();
  /** Vehicle id (seller payment), supplier id or customer id. */
  readonly targetId = input.required<string>();
  readonly owed = input.required<string>();
  readonly posted = output<void>();

  get kind(): PostingKind {
    return this.mode();
  }
  readonly dateControl = 'date';
  readonly noteControl = 'notes';
  readonly form = inject(NonNullableFormBuilder).group({
    amount: ['', [Validators.required, positiveMoney]],
    cash_account_id: ['', Validators.required],
    date: ['', Validators.required],
    notes: [''],
  });

  protected reset(): void {
    this.form.reset({
      amount: this.owed(),
      cash_account_id: this.defaultAccountId(),
      date: this.format.todayIso(),
      notes: '',
    });
  }

  protected body(): PaymentBody {
    const v = this.form.getRawValue();
    return { date: v.date, amount: v.amount, cash_account_id: v.cash_account_id, notes: v.notes.trim() || null };
  }

  protected previewCall(body: PaymentBody): Promise<Preview> {
    const { date, ...rest } = body;
    switch (this.mode()) {
      case 'sellerPayment':
        return this.vehiclesApi.previewSellerPayment(this.targetId(), { ...rest, payment_date: date });
      case 'supplierPayment':
        return this.suppliersApi.previewPayment(this.targetId(), { ...rest, payment_date: date });
      default:
        return this.customersApi.previewRefund(this.targetId(), { ...rest, refund_date: date });
    }
  }

  protected postCall(body: PaymentBody, key: string): Promise<unknown> {
    const { date, ...rest } = body;
    switch (this.mode()) {
      case 'sellerPayment':
        return this.vehiclesApi.recordSellerPayment(this.targetId(), { ...rest, payment_date: date }, key);
      case 'supplierPayment':
        return this.suppliersApi.recordPayment(this.targetId(), { ...rest, payment_date: date }, key);
      default:
        return this.customersApi.recordRefund(this.targetId(), { ...rest, refund_date: date }, key);
    }
  }

  protected emitPosted(): void {
    this.posted.emit();
  }
}
