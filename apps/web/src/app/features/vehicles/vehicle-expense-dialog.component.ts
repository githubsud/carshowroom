import { Component, computed, inject, input, output, signal } from '@angular/core';
import { FormsModule, NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';

import {
  ExpenseCategory,
  Preview,
  Supplier,
  VehicleExpenseInput,
  VehicleExpensePosting,
} from '../../core/api/api.models';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { PostingShellComponent } from '../../shared/components/posting-shell.component';
import { positiveMoney } from '../../shared/money-input';
import { loaded, translationsLoaded } from '../../shared/translated';
import { Option, PostingDialogBase, PostingKind } from '../finance/posting-dialog.base';
import { VehiclesService } from './vehicles.service';

type Funding = 'CASH_ACCOUNT' | 'SUPPLIER_CREDIT' | 'PARTNER';

/**
 * Quick vehicle expense (rules 9, 30, 31; P-04 once sold): tap a category,
 * type the amount, review, confirm. Date and cash box default, so a phone
 * user at the lot finishes in seconds (BACKLOG 4.7).
 */
@Component({
  selector: 'app-vehicle-expense-dialog',
  imports: [
    FormsModule,
    ReactiveFormsModule,
    TranslocoPipe,
    InputTextModule,
    SelectModule,
    SelectButtonModule,
    MoneyInputComponent,
    PostingShellComponent,
  ],
  template: `
    <app-posting-shell [visible]="visible()" [header]="'vehicles.expenseTitle' | transloco" [form]="form"
                       [step]="step()" [preview]="preview()" [error]="error()" [busy]="busy()"
                       testId="vehicle-expense-form" (review)="review()" (confirm)="confirm()" (back)="back()"
                       (dismiss)="visible.set(false)">
      <div class="dialog-fields" [formGroup]="form">
        <div class="field">
          <span class="chip-label" id="ve-category">{{ 'finance.category' | transloco }}</span>
          <p-selectbutton formControlName="category_id" [options]="categoryChips()" optionLabel="label" ariaLabelledBy="ve-category"
                          optionValue="value" [allowEmpty]="false" styleClass="chips" data-testid="expense-chips" />
        </div>
        <div class="field">
          <label for="ve-amount">{{ 'finance.amount' | transloco }}</label>
          <app-money-input inputId="ve-amount" formControlName="amount" data-testid="amount" />
        </div>
        <p-selectbutton [options]="fundingChoices()" [ngModel]="fundingKind()" [ngModelOptions]="{ standalone: true }"
                        (ngModelChange)="setFundingKind($event)" optionLabel="label" optionValue="value"
                        [allowEmpty]="false" data-testid="funding" />
        @switch (fundingKind()) {
          @case ('CASH_ACCOUNT') {
            <div class="field">
              <label for="ve-cash">{{ 'finance.paidFrom' | transloco }}</label>
              <p-select inputId="ve-cash" formControlName="cash_account_id" [options]="accountOptions()"
                        optionLabel="label" optionValue="value" [fluid]="true" />
            </div>
          }
          @case ('SUPPLIER_CREDIT') {
            <div class="field">
              <label for="ve-supplier">{{ 'vehicles.supplier' | transloco }}</label>
              <p-select inputId="ve-supplier" formControlName="supplier_id" [options]="supplierOptions()"
                        optionLabel="label" optionValue="value" [fluid]="true" [filter]="true"
                        data-testid="expense-supplier" />
            </div>
          }
          @case ('PARTNER') {
            <div class="row">
              <div class="field">
                <label for="ve-partner">{{ 'finance.paidByPartner' | transloco }}</label>
                <p-select inputId="ve-partner" formControlName="paid_by_partner_id" [options]="partnerOptions()"
                          optionLabel="label" optionValue="value" [fluid]="true" />
              </div>
              <div class="field">
                <label for="ve-mode">{{ 'finance.partnerFundingMode' | transloco }}</label>
                <p-select inputId="ve-mode" formControlName="partner_funding_mode" [options]="modeOptions()"
                          optionLabel="label" optionValue="value" [fluid]="true" />
              </div>
            </div>
          }
        }
        <div class="row">
          <div class="field">
            <label for="ve-date">{{ 'finance.date' | transloco }}</label>
            <input pInputText id="ve-date" type="date" formControlName="expense_date" />
          </div>
          <div class="field">
            <label for="ve-note">{{ 'finance.note' | transloco }}</label>
            <input pInputText id="ve-note" formControlName="description" />
          </div>
        </div>
      </div>
    </app-posting-shell>
  `,
  styles: `
    .chip-label {
      font-size: 0.875rem;
      font-weight: 600;
    }
    :host ::ng-deep .chips {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-1);
    }
  `,
})
export class VehicleExpenseDialogComponent extends PostingDialogBase<VehicleExpenseInput, VehicleExpensePosting> {
  private readonly api = inject(VehiclesService);
  private readonly transloco = inject(TranslocoService);
  private readonly translations = translationsLoaded();

  readonly vehicleId = input.required<string>();
  readonly categories = input.required<ExpenseCategory[]>();
  readonly suppliers = input<Supplier[]>([]);
  readonly posted = output<VehicleExpensePosting>();

  readonly kind: PostingKind = 'vehicleExpense';
  readonly dateControl = 'expense_date';
  readonly noteControl = 'description';
  readonly form = inject(NonNullableFormBuilder).group({
    expense_date: ['', Validators.required],
    category_id: ['', Validators.required],
    amount: ['', [Validators.required, positiveMoney]],
    cash_account_id: [''],
    supplier_id: [''],
    paid_by_partner_id: [''],
    partner_funding_mode: ['CURRENT_ACCOUNT' as 'CURRENT_ACCOUNT' | 'LOAN'],
    description: [''],
  });

  protected readonly fundingKind = signal<Funding>('CASH_ACCOUNT');
  protected readonly categoryChips = computed<Option[]>(() =>
    this.categories().map((c) => ({ value: c.id, label: this.name(c) })),
  );
  protected readonly supplierOptions = computed<Option[]>(() =>
    this.suppliers().map((s) => ({ value: s.id, label: s.name })),
  );
  protected readonly fundingChoices = computed<Option[]>(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    const choices = [{ value: 'CASH_ACCOUNT', label: this.transloco.translate('vehicles.fundingCash') }];
    if (this.suppliers().length > 0) {
      choices.push({ value: 'SUPPLIER_CREDIT', label: this.transloco.translate('vehicles.fundingSupplier') });
    }
    if (this.partners().length > 0) {
      choices.push({ value: 'PARTNER', label: this.transloco.translate('finance.fundingPartner') });
    }
    return choices;
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

  protected setFundingKind(value: Funding): void {
    this.fundingKind.set(value);
    const c = this.form.controls;
    c.cash_account_id.setValidators(value === 'CASH_ACCOUNT' ? Validators.required : null);
    c.supplier_id.setValidators(value === 'SUPPLIER_CREDIT' ? Validators.required : null);
    c.paid_by_partner_id.setValidators(value === 'PARTNER' ? Validators.required : null);
    for (const control of [c.cash_account_id, c.supplier_id, c.paid_by_partner_id]) {
      control.updateValueAndValidity();
    }
  }

  protected reset(): void {
    this.form.reset({
      expense_date: this.format.todayIso(),
      category_id: '',
      amount: '',
      cash_account_id: this.defaultAccountId(),
      supplier_id: '',
      paid_by_partner_id: '',
      partner_funding_mode: 'CURRENT_ACCOUNT',
      description: '',
    });
    this.setFundingKind('CASH_ACCOUNT');
  }

  protected body(): VehicleExpenseInput {
    const v = this.form.getRawValue();
    const base = {
      expense_date: v.expense_date,
      category_id: v.category_id,
      amount: v.amount,
      description: v.description.trim() || null,
      funding: this.fundingKind(),
    };
    switch (this.fundingKind()) {
      case 'SUPPLIER_CREDIT':
        return { ...base, supplier_id: v.supplier_id };
      case 'PARTNER':
        return { ...base, paid_by_partner_id: v.paid_by_partner_id, partner_funding_mode: v.partner_funding_mode };
      default:
        return { ...base, cash_account_id: v.cash_account_id };
    }
  }

  protected previewCall(body: VehicleExpenseInput): Promise<Preview> {
    return this.api.previewExpense(this.vehicleId(), body);
  }

  protected postCall(body: VehicleExpenseInput, key: string): Promise<VehicleExpensePosting> {
    return this.api.recordExpense(this.vehicleId(), body, key);
  }

  protected emitPosted(result: VehicleExpensePosting): void {
    this.posted.emit(result);
  }
}
