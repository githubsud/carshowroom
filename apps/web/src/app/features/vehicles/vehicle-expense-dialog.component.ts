import { Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule, NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { CheckboxModule } from 'primeng/checkbox';
import { InputTextModule } from 'primeng/inputtext';
import { MultiSelectModule } from 'primeng/multiselect';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';

import {
  ExpenseCategory,
  Preview,
  SplitVehicleExpenseInput,
  SplitVehicleExpensePosting,
  Supplier,
  VehicleExpenseInput,
  VehicleExpensePosting,
  VehicleRow,
} from '../../core/api/api.models';
import { MoneyPipe } from '../../core/format/format.service';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { PostingShellComponent } from '../../shared/components/posting-shell.component';
import { positiveMoney } from '../../shared/money-input';
import { moneyMinus, splitByWeights } from '../../shared/money-math';
import { loaded, translationsLoaded } from '../../shared/translated';
import { Option, PostingDialogBase, PostingKind } from '../finance/posting-dialog.base';
import { VehiclesService } from './vehicles.service';

type Funding = 'CASH_ACCOUNT' | 'SUPPLIER_CREDIT' | 'PARTNER';
type Body = VehicleExpenseInput | SplitVehicleExpenseInput;
type Result = VehicleExpensePosting | SplitVehicleExpensePosting;
/** The statuses a car can still take an expense in. */
const WITH_US = ['DRAFT', 'IN_PREPARATION', 'AVAILABLE', 'RESERVED', 'AT_OTHER_SHOWROOM', 'SOLD', 'DELIVERED'] as const;

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
    CheckboxModule,
    MultiSelectModule,
    MoneyInputComponent,
    MoneyPipe,
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
        <div class="split-toggle">
          <p-checkbox inputId="ve-split" [binary]="true" [ngModel]="split()" [ngModelOptions]="{ standalone: true }"
                      (ngModelChange)="setSplit($event)" data-testid="expense-split" />
          <label for="ve-split">{{ 'vehicles.splitExpense' | transloco }}</label>
        </div>
        @if (split()) {
          <div class="field">
            <label for="ve-cars">{{ 'vehicles.splitWith' | transloco }}</label>
            <p-multiselect inputId="ve-cars" [options]="carOptions()" optionLabel="label" optionValue="value"
                           [ngModel]="otherCars()" [ngModelOptions]="{ standalone: true }" (ngModelChange)="setOtherCars($event)"
                           [filter]="true" display="chip" [fluid]="true" data-testid="expense-split-cars" />
          </div>
          <div class="shares" data-testid="expense-shares">
            @for (row of shareRows(); track row.id) {
              <div class="share">
                <span>{{ row.label }}</span>
                <app-money-input [ngModel]="shares()[row.id] ?? ''" [ngModelOptions]="{ standalone: true }"
                                 (ngModelChange)="setShare(row.id, $event)" [attr.data-testid]="'share-' + row.id" />
              </div>
            }
            @if (shareGap() !== '0.00') {
              <p class="gap" data-testid="expense-share-gap">{{ 'vehicles.splitGap' | transloco }}: {{ shareGap() | money }}</p>
            }
          </div>
        }
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
    .split-toggle {
      display: flex;
      gap: var(--space-2);
      align-items: center;
    }
    .shares {
      display: grid;
      gap: var(--space-1);
    }
    .share {
      display: grid;
      grid-template-columns: 1fr 10rem;
      gap: var(--space-2);
      align-items: center;
    }
    .gap {
      margin: 0;
      color: var(--color-danger, #dc2626);
    }
    :host ::ng-deep .chips {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-1);
    }
  `,
})
export class VehicleExpenseDialogComponent extends PostingDialogBase<Body, Result> {
  private readonly api = inject(VehiclesService);
  private readonly transloco = inject(TranslocoService);
  private readonly translations = translationsLoaded();

  readonly vehicleId = input.required<string>();
  readonly categories = input.required<ExpenseCategory[]>();
  readonly suppliers = input<Supplier[]>([]);
  readonly posted = output<Result>();

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

  // --- One expense over several cars (pilot review, D-71) ---------------------------------
  protected readonly split = signal(false);
  private readonly cars = signal<VehicleRow[]>([]);
  protected readonly otherCars = signal<string[]>([]);
  /** Each car's part, keyed by vehicle id; filled with an equal split, then editable. */
  protected readonly shares = signal<Record<string, string>>({});
  private readonly total = signal('');
  protected readonly carOptions = computed<Option[]>(() =>
    this.cars()
      .filter((c) => c.id !== this.vehicleId())
      .map((c) => ({ value: c.id, label: `${c.make} ${c.model} ${c.year ?? ''} — ${c.stock_no}` })),
  );
  protected readonly shareRows = computed(() => {
    const labels = new Map(this.carOptions().map((o) => [o.value, o.label]));
    return [this.vehicleId(), ...this.otherCars()].map((id) => ({
      id,
      label: id === this.vehicleId() ? this.transloco.translate('vehicles.thisCar') : (labels.get(id) ?? id),
    }));
  });
  protected readonly shareGap = computed(() => {
    const parts = this.shareRows().map((row) => this.shares()[row.id] || '0');
    return moneyMinus(this.total() || '0', ...parts);
  });
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

  constructor() {
    super();
    this.form.controls.amount.valueChanges.subscribe((value) => {
      this.total.set(value ?? '');
      this.spreadEvenly();
    });
    effect(() => {
      if (!this.visible()) {
        this.split.set(false);
        this.otherCars.set([]);
        this.shares.set({});
      }
    });
  }

  protected async setSplit(on: boolean): Promise<void> {
    this.split.set(on);
    if (on && this.cars().length === 0) {
      const page = await this.api.list({ status: WITH_US, page_size: 100, sort: '-created' });
      this.cars.set(page.items);
    }
    this.spreadEvenly();
  }

  protected setOtherCars(ids: string[]): void {
    this.otherCars.set(ids);
    this.spreadEvenly();
  }

  protected setShare(id: string, value: string): void {
    this.shares.update((current) => ({ ...current, [id]: value ?? '' }));
  }

  private spreadEvenly(): void {
    const ids = [this.vehicleId(), ...this.otherCars()];
    const total = this.total();
    if (!this.split() || !total || Number.isNaN(Number(total))) {
      return;
    }
    const parts = splitByWeights(total, ids.map(() => '1'));
    this.shares.set(Object.fromEntries(ids.map((id, i) => [id, parts[i]])));
  }

  protected override async review(): Promise<void> {
    if (this.split() && (this.otherCars().length === 0 || this.shareGap() !== '0.00')) {
      this.error.set(this.transloco.translate('vehicles.splitInvalid'));
      return;
    }
    await super.review();
  }

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

  protected body(): Body {
    const v = this.form.getRawValue();
    const base = {
      expense_date: v.expense_date,
      category_id: v.category_id,
      description: v.description.trim() || null,
      funding: this.fundingKind(),
    };
    const funding =
      this.fundingKind() === 'SUPPLIER_CREDIT'
        ? { supplier_id: v.supplier_id }
        : this.fundingKind() === 'PARTNER'
          ? { paid_by_partner_id: v.paid_by_partner_id, partner_funding_mode: v.partner_funding_mode }
          : { cash_account_id: v.cash_account_id };
    if (this.split()) {
      const shares = this.shareRows().map((row) => ({ vehicle_id: row.id, amount: this.shares()[row.id] }));
      return { ...base, ...funding, shares };
    }
    return { ...base, ...funding, amount: v.amount };
  }

  protected previewCall(body: Body): Promise<Preview> {
    return 'shares' in body ? this.api.previewSplitExpense(body) : this.api.previewExpense(this.vehicleId(), body);
  }

  protected postCall(body: Body, key: string): Promise<Result> {
    return 'shares' in body ? this.api.recordSplitExpense(body, key) : this.api.recordExpense(this.vehicleId(), body, key);
  }

  protected emitPosted(result: Result): void {
    this.posted.emit(result);
  }
}
