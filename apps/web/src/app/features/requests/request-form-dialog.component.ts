import { Component, effect, inject, input, model, output, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';

import { CustomerRequest } from '../../core/api/api.models';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { CustomerPickerComponent } from '../customers/customer-picker.component';
import { CrmService } from './crm.service';

/** A customer asks for a car we do not have yet (SPEC §4.6). */
@Component({
  selector: 'app-request-form-dialog',
  imports: [
    ReactiveFormsModule,
    TranslocoPipe,
    ButtonModule,
    CheckboxModule,
    DialogModule,
    InputTextModule,
    MessageModule,
    MoneyInputComponent,
    CustomerPickerComponent,
  ],
  template: `
    <p-dialog [visible]="visible()" (visibleChange)="visible.set($event)" [modal]="true"
              [header]="'requests.add' | transloco" [style]="{ width: 'min(520px, 96vw)' }">
      <form class="dialog-fields" [formGroup]="form" (ngSubmit)="save()" data-testid="request-form">
        @if (!customerId()) {
          <div class="field">
            <label for="rq-customer">{{ 'sales.customer' | transloco }}</label>
            <app-customer-picker inputId="rq-customer" formControlName="customer_id" testId="rq-customer" />
          </div>
        }
        <div class="row">
          <div class="field">
            <label for="rq-make">{{ 'vehicles.make' | transloco }}</label>
            <input pInputText id="rq-make" formControlName="make" data-testid="rq-make" />
          </div>
          <div class="field">
            <label for="rq-model">{{ 'vehicles.model' | transloco }}</label>
            <input pInputText id="rq-model" formControlName="model" data-testid="rq-model" />
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label for="rq-from">{{ 'requests.yearFrom' | transloco }}</label>
            <input pInputText id="rq-from" type="number" inputmode="numeric" formControlName="year_from" />
          </div>
          <div class="field">
            <label for="rq-to">{{ 'requests.yearTo' | transloco }}</label>
            <input pInputText id="rq-to" type="number" inputmode="numeric" formControlName="year_to" />
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label for="rq-min">{{ 'requests.budgetMin' | transloco }}</label>
            <app-money-input inputId="rq-min" formControlName="budget_min" />
          </div>
          <div class="field">
            <label for="rq-max">{{ 'requests.budgetMax' | transloco }}</label>
            <app-money-input inputId="rq-max" formControlName="budget_max" data-testid="rq-budget" />
          </div>
        </div>
        <div class="field">
          <label for="rq-color">{{ 'requests.color' | transloco }}</label>
          <input pInputText id="rq-color" formControlName="color_pref" />
        </div>
        <div class="field">
          <label for="rq-notes">{{ 'finance.note' | transloco }}</label>
          <input pInputText id="rq-notes" formControlName="notes" />
        </div>
        <div class="checks">
          <span class="check"><p-checkbox formControlName="financing_needed" [binary]="true" inputId="rq-fin" />
            <label for="rq-fin">{{ 'requests.financing' | transloco }}</label></span>
          <span class="check"><p-checkbox formControlName="trade_in_offered" [binary]="true" inputId="rq-trade" />
            <label for="rq-trade">{{ 'requests.tradeIn' | transloco }}</label></span>
        </div>
        @if (error()) {
          <p-message severity="error" data-testid="dialog-error">{{ error() }}</p-message>
        }
        <div class="actions">
          <p-button type="button" [text]="true" [label]="'common.cancel' | transloco" (onClick)="visible.set(false)" />
          <p-button type="submit" [label]="'settings.save' | transloco" [loading]="busy()" data-testid="rq-save" />
        </div>
      </form>
    </p-dialog>
  `,
  styles: `
    .actions {
      display: flex;
      gap: var(--space-2);
      justify-content: flex-end;
    }
    .checks {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-3);
    }
    .check {
      display: flex;
      gap: var(--space-2);
      align-items: center;
    }
  `,
})
export class RequestFormDialogComponent {
  private readonly api = inject(CrmService);
  private readonly errors = inject(ErrorMessageService);

  readonly visible = model(false);
  /** Fixed customer (from the customer page); otherwise picked in the form. */
  readonly customerId = input<string | null>(null);
  readonly saved = output<CustomerRequest>();

  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly form = inject(NonNullableFormBuilder).group({
    customer_id: [''],
    make: [''],
    model: [''],
    year_from: [''],
    year_to: [''],
    budget_min: [''],
    budget_max: [''],
    color_pref: [''],
    notes: [''],
    financing_needed: [false],
    trade_in_offered: [false],
  });

  constructor() {
    effect(() => {
      if (this.visible()) {
        this.error.set(null);
        this.form.reset();
      }
    });
  }

  protected async save(): Promise<void> {
    const v = this.form.getRawValue();
    const customer = this.customerId() ?? v.customer_id;
    const text = (value: string) => value.trim() || null;
    const year = (value: string) => (String(value).trim() ? Number(value) : null);
    this.busy.set(true);
    this.error.set(null);
    try {
      const request = await this.api.createRequest({
        customer_id: customer,
        make: text(v.make),
        model: text(v.model),
        year_from: year(v.year_from),
        year_to: year(v.year_to),
        budget_min: text(v.budget_min),
        budget_max: text(v.budget_max),
        color_pref: text(v.color_pref),
        notes: text(v.notes),
        financing_needed: v.financing_needed,
        trade_in_offered: v.trade_in_offered,
      });
      this.visible.set(false);
      this.saved.emit(request);
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }
}
