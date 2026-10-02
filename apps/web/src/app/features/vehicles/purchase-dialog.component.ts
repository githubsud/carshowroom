import { Component, computed, inject, input, output } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { CheckboxModule } from 'primeng/checkbox';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';

import { Preview, PurchaseInput, PurchasePosting } from '../../core/api/api.models';
import { MoneyPipe } from '../../core/format/format.service';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { PostingShellComponent } from '../../shared/components/posting-shell.component';
import { moneyMinus } from '../../shared/money-math';
import { positiveMoney } from '../../shared/money-input';
import { CustomerPickerComponent } from '../customers/customer-picker.component';
import { PostingDialogBase, PostingKind } from '../finance/posting-dialog.base';
import { VehiclesService } from './vehicles.service';

/**
 * Record the purchase of a car (rules 6, 7): seller, price, what is paid now
 * and from where; the rest is owed to the seller and paid later (rule 8).
 */
@Component({
  selector: 'app-purchase-dialog',
  imports: [
    ReactiveFormsModule,
    TranslocoPipe,
    CheckboxModule,
    InputTextModule,
    SelectModule,
    MoneyInputComponent,
    MoneyPipe,
    PostingShellComponent,
    CustomerPickerComponent,
  ],
  template: `
    <app-posting-shell [visible]="visible()" [header]="'vehicles.purchaseTitle' | transloco" [form]="form"
                       [step]="step()" [preview]="preview()" [error]="error()" [busy]="busy()"
                       testId="purchase-form" (review)="review()" (confirm)="confirm()" (back)="back()"
                       (dismiss)="visible.set(false)">
      <div class="dialog-fields" [formGroup]="form">
        <div class="field">
          <label for="seller">{{ 'vehicles.seller' | transloco }}</label>
          <app-customer-picker inputId="seller" formControlName="seller_customer_id" testId="seller-picker" />
        </div>
        <div class="row">
          <div class="field">
            <label for="price">{{ 'vehicles.purchasePrice' | transloco }}</label>
            <app-money-input inputId="price" formControlName="price" data-testid="purchase-price" />
          </div>
          <div class="field">
            <label for="paid">{{ 'vehicles.paidNow' | transloco }}</label>
            <app-money-input inputId="paid" formControlName="paid" data-testid="paid-now" />
          </div>
        </div>
        <div class="field">
          <label for="p-cash">{{ 'finance.paidFrom' | transloco }}</label>
          <p-select inputId="p-cash" formControlName="cash_account_id" [options]="accountOptions()" optionLabel="label"
                    optionValue="value" [fluid]="true" />
        </div>
        @if (deferred() !== '0.00') {
          <p class="hint" data-testid="deferred">{{ 'vehicles.owedToSeller' | transloco }}: {{ deferred() | money }}</p>
        }
        <div class="field">
          <label for="p-date">{{ 'vehicles.purchaseDate' | transloco }}</label>
          <input pInputText id="p-date" type="date" formControlName="purchase_date" />
        </div>
        <div class="check">
          <p-checkbox formControlName="ready_for_sale" [binary]="true" inputId="ready" />
          <label for="ready">{{ 'vehicles.readyForSale' | transloco }}</label>
        </div>
      </div>
    </app-posting-shell>
  `,
  styles: `
    .hint {
      margin: 0;
      color: var(--color-text-muted);
    }
    .check {
      display: flex;
      gap: var(--space-2);
      align-items: center;
      font-weight: 400;
    }
  `,
})
export class PurchaseDialogComponent extends PostingDialogBase<PurchaseInput, PurchasePosting> {
  private readonly api = inject(VehiclesService);

  readonly vehicleId = input.required<string>();
  readonly posted = output<PurchasePosting>();

  readonly kind: PostingKind = 'purchase';
  readonly dateControl = 'purchase_date';
  readonly noteControl = 'notes';
  readonly form = inject(NonNullableFormBuilder).group({
    seller_customer_id: ['', Validators.required],
    price: ['', [Validators.required, positiveMoney]],
    paid: [''],
    cash_account_id: [''],
    purchase_date: ['', Validators.required],
    ready_for_sale: [false],
    notes: [''],
  });

  private readonly values = toSignal(this.form.valueChanges, { initialValue: this.form.getRawValue() });
  protected readonly deferred = computed(() => {
    const v = this.values();
    return moneyMinus(v.price, v.paid);
  });

  protected reset(): void {
    this.form.reset({
      seller_customer_id: '',
      price: '',
      paid: '',
      cash_account_id: this.defaultAccountId(),
      purchase_date: this.format.todayIso(),
      ready_for_sale: false,
      notes: '',
    });
  }

  protected body(): PurchaseInput {
    const v = this.form.getRawValue();
    const paid = v.paid && !/^0*(\.0*)?$/.test(v.paid) ? v.paid : null;
    return {
      seller_customer_id: v.seller_customer_id,
      purchase_date: v.purchase_date,
      price: v.price,
      payments: paid ? [{ cash_account_id: v.cash_account_id, amount: paid }] : [],
      ready_for_sale: v.ready_for_sale,
      notes: v.notes.trim() || null,
    };
  }

  protected previewCall(body: PurchaseInput): Promise<Preview> {
    return this.api.previewPurchase(this.vehicleId(), body);
  }

  protected postCall(body: PurchaseInput, key: string): Promise<PurchasePosting> {
    return this.api.recordPurchase(this.vehicleId(), body, key);
  }

  protected emitPosted(result: PurchasePosting): void {
    this.posted.emit(result);
  }
}
