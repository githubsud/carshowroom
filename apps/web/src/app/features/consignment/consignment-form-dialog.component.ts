import { Component, computed, effect, inject, model, output, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';

import { Consignment } from '../../core/api/api.models';
import { FormatService } from '../../core/format/format.service';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { positiveMoney } from '../../shared/money-input';
import { loaded, translationsLoaded } from '../../shared/translated';
import { CustomerPickerComponent } from '../customers/customer-picker.component';
import { ConsignmentService } from './consignment.service';

type Terms = 'NET_PRICE' | 'COMMISSION_FIXED' | 'COMMISSION_PCT';
type Borne = 'OWNER' | 'SHOWROOM' | 'SHARED';

/** Receive a car on consignment (SPEC §4.4): the owner, the car, and the agreed terms in one form. */
@Component({
  selector: 'app-consignment-form-dialog',
  imports: [
    ReactiveFormsModule,
    TranslocoPipe,
    ButtonModule,
    DialogModule,
    InputTextModule,
    MessageModule,
    SelectModule,
    SelectButtonModule,
    MoneyInputComponent,
    CustomerPickerComponent,
  ],
  template: `
    <p-dialog [visible]="visible()" (visibleChange)="visible.set($event)" [modal]="true"
              [header]="'consignment.receive' | transloco" [style]="{ width: 'min(600px, 96vw)' }">
      <form class="dialog-fields" [formGroup]="form" (ngSubmit)="save()" data-testid="consignment-form">
        <div class="field">
          <label for="cf-owner">{{ 'consignment.owner' | transloco }}</label>
          <app-customer-picker inputId="cf-owner" formControlName="consignor_id" testId="cf-owner" />
        </div>
        <h3>{{ 'vehicles.vehicle' | transloco }}</h3>
        <div class="row">
          <div class="field">
            <label for="cf-make">{{ 'vehicles.make' | transloco }}</label>
            <input pInputText id="cf-make" formControlName="make" data-testid="cf-make" />
          </div>
          <div class="field">
            <label for="cf-model">{{ 'vehicles.model' | transloco }}</label>
            <input pInputText id="cf-model" formControlName="model" data-testid="cf-model" />
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label for="cf-year">{{ 'vehicles.year' | transloco }}</label>
            <input pInputText id="cf-year" type="number" inputmode="numeric" formControlName="year" />
          </div>
          <div class="field">
            <label for="cf-plate">{{ 'vehicles.plate' | transloco }}</label>
            <input pInputText id="cf-plate" formControlName="plate_no" />
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label for="cf-vin">{{ 'vehicles.vin' | transloco }}</label>
            <input pInputText id="cf-vin" formControlName="vin" dir="ltr" />
          </div>
          <div class="field">
            <label for="cf-asking">{{ 'vehicles.askingPrice' | transloco }}</label>
            <app-money-input inputId="cf-asking" formControlName="asking_price" data-testid="cf-asking" />
          </div>
        </div>
        <h3>{{ 'consignment.terms' | transloco }}</h3>
        <p-selectbutton formControlName="terms_type" [options]="termOptions()" optionLabel="label" optionValue="value"
                        [allowEmpty]="false" data-testid="cf-terms" />
        <div class="row">
          <div class="field">
            <label for="cf-value">{{ valueLabel() | transloco }}</label>
            <app-money-input inputId="cf-value" formControlName="value" data-testid="cf-value" />
          </div>
          <div class="field">
            <label for="cf-borne">{{ 'consignment.expensesBorneBy' | transloco }}</label>
            <p-select inputId="cf-borne" formControlName="expenses_borne_by" [options]="borneOptions()"
                      optionLabel="label" optionValue="value" [fluid]="true" />
          </div>
        </div>
        @if (values().expenses_borne_by === 'SHARED') {
          <div class="field">
            <label for="cf-pct">{{ 'consignment.ownerPct' | transloco }}</label>
            <input pInputText id="cf-pct" type="number" inputmode="decimal" formControlName="shared_owner_pct" />
          </div>
        }
        <div class="row">
          <div class="field">
            <label for="cf-date">{{ 'consignment.agreementDate' | transloco }}</label>
            <input pInputText id="cf-date" type="date" formControlName="agreement_date" />
          </div>
          <div class="field">
            <label for="cf-end">{{ 'consignment.endDate' | transloco }}</label>
            <input pInputText id="cf-end" type="date" formControlName="end_date" />
          </div>
        </div>
        <div class="field">
          <label for="cf-notes">{{ 'finance.note' | transloco }}</label>
          <input pInputText id="cf-notes" formControlName="notes" />
        </div>
        @if (error()) {
          <p-message severity="error" data-testid="dialog-error">{{ error() }}</p-message>
        }
        <div class="actions">
          <p-button type="button" [text]="true" [label]="'common.cancel' | transloco" (onClick)="visible.set(false)" />
          <p-button type="submit" [label]="'settings.save' | transloco" [loading]="busy()" data-testid="cf-save" />
        </div>
      </form>
    </p-dialog>
  `,
  styles: `
    h3 {
      margin: var(--space-2) 0 0;
      font-size: 1rem;
    }
    .actions {
      display: flex;
      gap: var(--space-2);
      justify-content: flex-end;
    }
  `,
})
export class ConsignmentFormDialogComponent {
  private readonly api = inject(ConsignmentService);
  private readonly errors = inject(ErrorMessageService);
  private readonly format = inject(FormatService);
  private readonly transloco = inject(TranslocoService);
  private readonly translations = translationsLoaded();

  readonly visible = model(false);
  readonly saved = output<Consignment>();

  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly form = inject(NonNullableFormBuilder).group({
    consignor_id: ['', Validators.required],
    make: ['', Validators.required],
    model: ['', Validators.required],
    year: [''],
    plate_no: [''],
    vin: [''],
    asking_price: [''],
    terms_type: ['COMMISSION_PCT' as Terms],
    value: ['', [Validators.required, positiveMoney]],
    expenses_borne_by: ['OWNER' as Borne],
    shared_owner_pct: [''],
    agreement_date: ['', Validators.required],
    end_date: [''],
    notes: [''],
  });
  protected readonly values = toSignal(this.form.valueChanges, { initialValue: this.form.getRawValue() });
  protected readonly valueLabel = computed(() => `consignment.value_${this.values().terms_type}`);
  protected readonly termOptions = computed(() =>
    loaded(this.translations())
      ? (['COMMISSION_PCT', 'COMMISSION_FIXED', 'NET_PRICE'] as Terms[]).map((value) => ({
          value,
          label: this.transloco.translate(`consignment.terms_${value}`),
        }))
      : [],
  );
  protected readonly borneOptions = computed(() =>
    loaded(this.translations())
      ? (['OWNER', 'SHOWROOM', 'SHARED'] as Borne[]).map((value) => ({
          value,
          label: this.transloco.translate(`consignment.borne_${value}`),
        }))
      : [],
  );

  constructor() {
    effect(() => {
      if (this.visible()) {
        this.error.set(null);
        this.form.reset({ agreement_date: this.format.todayIso() });
      }
    });
  }

  protected async save(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const v = this.form.getRawValue();
    const text = (value: string) => value.trim() || null;
    this.busy.set(true);
    this.error.set(null);
    try {
      const consignment = await this.api.create({
        consignor_id: v.consignor_id,
        vehicle: {
          make: v.make.trim(),
          model: v.model.trim(),
          year: String(v.year).trim() ? Number(v.year) : null,
          plate_no: text(v.plate_no),
          vin: text(v.vin),
          asking_price: text(v.asking_price),
          acquisition_source: 'DIRECT_PURCHASE',
        },
        agreement_date: v.agreement_date,
        end_date: v.end_date || null,
        terms_type: v.terms_type,
        net_price_to_owner: v.terms_type === 'NET_PRICE' ? v.value : null,
        commission_value: v.terms_type === 'NET_PRICE' ? null : v.value,
        expenses_borne_by: v.expenses_borne_by,
        shared_owner_pct: v.expenses_borne_by === 'SHARED' ? String(v.shared_owner_pct) : null,
        notes: text(v.notes),
      });
      this.visible.set(false);
      this.saved.emit(consignment);
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }
}
