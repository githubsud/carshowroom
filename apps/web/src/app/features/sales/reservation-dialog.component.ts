import { Component, inject, input, output } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';

import { Preview, ReservationInput, ReservationPosting } from '../../core/api/api.models';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { PostingShellComponent } from '../../shared/components/posting-shell.component';
import { positiveMoney } from '../../shared/money-input';
import { CustomerPickerComponent } from '../customers/customer-picker.component';
import { PostingDialogBase, PostingKind } from '../finance/posting-dialog.base';
import { SalesService } from './sales.service';

/** Reserve a car with a deposit (rule 11, عربون); the car becomes RESERVED. */
@Component({
  selector: 'app-reservation-dialog',
  imports: [ReactiveFormsModule, TranslocoPipe, InputTextModule, SelectModule, MoneyInputComponent, PostingShellComponent, CustomerPickerComponent],
  template: `
    <app-posting-shell [visible]="visible()" [header]="'sales.reserveTitle' | transloco" [form]="form" [step]="step()"
                       [preview]="preview()" [error]="error()" [busy]="busy()" testId="reservation-form"
                       (review)="review()" (confirm)="confirm()" (back)="back()" (dismiss)="visible.set(false)">
      <div class="dialog-fields" [formGroup]="form">
        <div class="field">
          <label for="r-customer">{{ 'sales.customer' | transloco }}</label>
          <app-customer-picker inputId="r-customer" formControlName="customer_id" testId="reservation-customer" />
        </div>
        <div class="field">
          <label for="r-amount">{{ 'sales.deposit' | transloco }}</label>
          <app-money-input inputId="r-amount" formControlName="deposit_amount" data-testid="amount" />
        </div>
        <div class="field">
          <label for="r-cash">{{ 'finance.receivedIn' | transloco }}</label>
          <p-select inputId="r-cash" formControlName="cash_account_id" [options]="accountOptions()" optionLabel="label"
                    optionValue="value" [fluid]="true" />
        </div>
        <div class="row">
          <div class="field">
            <label for="r-date">{{ 'finance.date' | transloco }}</label>
            <input pInputText id="r-date" type="date" formControlName="reservation_date" />
          </div>
          <div class="field">
            <label for="r-expiry">{{ 'sales.expiresOn' | transloco }}</label>
            <input pInputText id="r-expiry" type="date" formControlName="expires_on" />
          </div>
        </div>
      </div>
    </app-posting-shell>
  `,
})
export class ReservationDialogComponent extends PostingDialogBase<ReservationInput, ReservationPosting> {
  private readonly api = inject(SalesService);

  readonly vehicleId = input.required<string>();
  readonly posted = output<ReservationPosting>();

  readonly kind: PostingKind = 'reservation';
  readonly dateControl = 'reservation_date';
  readonly noteControl = 'notes';
  readonly form = inject(NonNullableFormBuilder).group({
    customer_id: ['', Validators.required],
    deposit_amount: ['', [Validators.required, positiveMoney]],
    cash_account_id: ['', Validators.required],
    reservation_date: ['', Validators.required],
    expires_on: [''],
    notes: [''],
  });

  protected reset(): void {
    const today = this.format.todayIso();
    const week = new Date(`${today}T00:00:00`);
    week.setDate(week.getDate() + 7);
    this.form.reset({
      customer_id: '',
      deposit_amount: '',
      cash_account_id: this.defaultAccountId(),
      reservation_date: today,
      expires_on: `${week.getFullYear()}-${String(week.getMonth() + 1).padStart(2, '0')}-${String(week.getDate()).padStart(2, '0')}`,
      notes: '',
    });
  }

  protected body(): ReservationInput {
    const v = this.form.getRawValue();
    return {
      vehicle_id: this.vehicleId(),
      customer_id: v.customer_id,
      deposit_amount: v.deposit_amount,
      cash_account_id: v.cash_account_id,
      reservation_date: v.reservation_date,
      expires_on: v.expires_on || null,
      notes: v.notes.trim() || null,
    };
  }

  protected previewCall(body: ReservationInput): Promise<Preview> {
    return this.api.previewReservation(body);
  }

  protected postCall(body: ReservationInput, key: string): Promise<ReservationPosting> {
    return this.api.reserve(body, key);
  }

  protected emitPosted(result: ReservationPosting): void {
    this.posted.emit(result);
  }
}
