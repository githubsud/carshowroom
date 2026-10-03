import { Component, computed, effect, inject, input, model, output, signal, untracked } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectModule } from 'primeng/select';

import { Location, Vehicle, VehicleInput } from '../../core/api/api.models';
import { LanguageService } from '../../core/i18n/language.service';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { positiveMoney } from '../../shared/money-input';
import { loaded, translationsLoaded } from '../../shared/translated';
import { VehiclesService } from './vehicles.service';

const TRANSMISSIONS = ['AUTOMATIC', 'MANUAL', 'CVT', 'OTHER'] as const;
const FUELS = ['PETROL', 'DIESEL', 'HYBRID', 'ELECTRIC', 'NATURAL_GAS', 'OTHER'] as const;

function optionalMoney(control: { value: string }): ReturnType<typeof positiveMoney> {
  return control.value ? positiveMoney(control as never) : null;
}

/** Add or edit a car's details (SPEC §4.3). All writes go through the API (D-06). */
@Component({
  selector: 'app-vehicle-form-dialog',
  imports: [ReactiveFormsModule, TranslocoPipe, ButtonModule, DialogModule, InputTextModule, MessageModule, SelectModule, MoneyInputComponent],
  template: `
    <p-dialog [visible]="visible()" (visibleChange)="visible.set($event)" [modal]="true"
              [header]="(vehicle() ? 'vehicles.edit' : 'vehicles.add') | transloco" [style]="{ width: 'min(640px, 96vw)' }">
      <form class="dialog-fields" [formGroup]="form" (ngSubmit)="save()" data-testid="vehicle-form">
        <div class="row">
          <div class="field">
            <label for="v-make">{{ 'vehicles.make' | transloco }}</label>
            <input pInputText id="v-make" formControlName="make" data-testid="vehicle-make" />
          </div>
          <div class="field">
            <label for="v-model">{{ 'vehicles.model' | transloco }}</label>
            <input pInputText id="v-model" formControlName="model" data-testid="vehicle-model" />
          </div>
          <div class="field">
            <label for="v-year">{{ 'vehicles.year' | transloco }}</label>
            <input pInputText id="v-year" formControlName="year" inputmode="numeric" dir="ltr" data-testid="vehicle-year" />
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label for="v-trim">{{ 'vehicles.trim' | transloco }}</label>
            <input pInputText id="v-trim" formControlName="trim" />
          </div>
          <div class="field">
            <label for="v-color">{{ 'vehicles.color' | transloco }}</label>
            <input pInputText id="v-color" formControlName="color_ext" />
          </div>
          <div class="field">
            <label for="v-km">{{ 'vehicles.mileage' | transloco }}</label>
            <input pInputText id="v-km" formControlName="mileage_km" inputmode="numeric" dir="ltr" />
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label for="v-trans">{{ 'vehicles.transmission' | transloco }}</label>
            <p-select inputId="v-trans" formControlName="transmission" [options]="transmissions()" optionLabel="label"
                      optionValue="value" [showClear]="true" [fluid]="true" />
          </div>
          <div class="field">
            <label for="v-fuel">{{ 'vehicles.fuel' | transloco }}</label>
            <p-select inputId="v-fuel" formControlName="fuel" [options]="fuels()" optionLabel="label" optionValue="value"
                      [showClear]="true" [fluid]="true" />
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label for="v-vin">{{ 'vehicles.vin' | transloco }}</label>
            <input pInputText id="v-vin" formControlName="vin" dir="ltr" data-testid="vehicle-vin" />
          </div>
          <div class="field">
            <label for="v-plate">{{ 'vehicles.plate' | transloco }}</label>
            <input pInputText id="v-plate" formControlName="plate_no" />
          </div>
          <div class="field">
            <label for="v-license">{{ 'vehicles.licenseExpiry' | transloco }}</label>
            <input pInputText id="v-license" type="date" formControlName="license_expiry" />
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label for="v-asking">{{ 'vehicles.askingPrice' | transloco }}</label>
            <app-money-input inputId="v-asking" formControlName="asking_price" data-testid="asking-price" />
          </div>
          @if (context.can('vehicle.view_min_price')) {
            <div class="field">
              <label for="v-min">{{ 'vehicles.minPrice' | transloco }}</label>
              <app-money-input inputId="v-min" formControlName="min_price" />
            </div>
          }
        </div>
        @if (!vehicle()) {
          <div class="field">
            <label for="v-location">{{ 'vehicles.location' | transloco }}</label>
            <p-select inputId="v-location" formControlName="current_location_id" [options]="locationOptions()"
                      optionLabel="label" optionValue="value" [fluid]="true" />
          </div>
        }
        <div class="field">
          <label for="v-notes">{{ 'finance.note' | transloco }}</label>
          <input pInputText id="v-notes" formControlName="notes" />
        </div>
        @if (error()) {
          <p-message severity="error" data-testid="dialog-error">{{ error() }}</p-message>
        }
        <div class="actions">
          <p-button type="button" [text]="true" [label]="'common.cancel' | transloco" (onClick)="visible.set(false)" />
          <p-button type="submit" [label]="(vehicle() ? 'settings.save' : 'vehicles.saveAndContinue') | transloco"
                    [loading]="busy()" data-testid="vehicle-save" />
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
  `,
})
export class VehicleFormDialogComponent {
  private readonly api = inject(VehiclesService);
  private readonly errors = inject(ErrorMessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly language = inject(LanguageService);
  private readonly translations = translationsLoaded();
  protected readonly context = inject(TenantContextService);

  readonly visible = model(false);
  readonly vehicle = input<Vehicle | null>(null);
  readonly locations = input<Location[]>([]);
  readonly saved = output<Vehicle>();

  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly form = inject(NonNullableFormBuilder).group({
    make: ['', Validators.required],
    model: ['', Validators.required],
    year: ['', Validators.pattern(/^(19[5-9]\d|20\d\d)$/)],
    trim: [''],
    color_ext: [''],
    mileage_km: ['', Validators.pattern(/^\d{1,7}$/)],
    transmission: [null as string | null],
    fuel: [null as string | null],
    vin: [''],
    plate_no: [''],
    license_expiry: [''],
    asking_price: ['', optionalMoney],
    min_price: ['', optionalMoney],
    current_location_id: [''],
    notes: [''],
  });

  protected readonly transmissions = computed(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    return TRANSMISSIONS.map((value) => ({ value, label: this.transloco.translate(`vehicles.transmission_${value}`) }));
  });
  protected readonly fuels = computed(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    return FUELS.map((value) => ({ value, label: this.transloco.translate(`vehicles.fuel_${value}`) }));
  });
  protected readonly locationOptions = computed(() =>
    this.locations().map((l) => ({
      value: l.id,
      label: this.language.language() === 'ar' ? l.name_ar : (l.name_en ?? l.name_ar),
    })),
  );

  constructor() {
    effect(() => {
      if (!this.visible()) {
        return;
      }
      const v = this.vehicle();
      this.error.set(null);
      this.form.reset({
        make: v?.make ?? '',
        model: v?.model ?? '',
        year: v?.year ? String(v.year) : '',
        trim: v?.trim ?? '',
        color_ext: v?.color_ext ?? '',
        mileage_km: v?.mileage_km != null ? String(v.mileage_km) : '',
        transmission: v?.transmission ?? null,
        fuel: v?.fuel ?? null,
        vin: v?.vin ?? '',
        plate_no: v?.plate_no ?? '',
        license_expiry: v?.license_expiry ?? '',
        asking_price: v?.asking_price ?? '',
        min_price: v?.min_price ?? '',
        current_location_id: untracked(() => this.defaultLocation()),
        notes: v?.notes ?? '',
      });
    });
    // Locations may arrive after the dialog opened: fill the default in without
    // resetting what the user has typed meanwhile.
    effect(() => {
      const fallback = this.defaultLocation();
      const control = this.form.controls.current_location_id;
      if (fallback && !control.value) {
        control.setValue(fallback);
      }
    });
  }

  private defaultLocation(): string {
    return this.locations().find((l) => l.is_default)?.id ?? '';
  }

  protected async save(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const v = this.form.getRawValue();
    const body: Omit<VehicleInput, 'acquisition_source' | 'current_location_id'> = {
      make: v.make.trim(),
      model: v.model.trim(),
      year: v.year ? Number(v.year) : null,
      trim: v.trim.trim() || null,
      color_ext: v.color_ext.trim() || null,
      mileage_km: v.mileage_km ? Number(v.mileage_km) : null,
      transmission: (v.transmission as VehicleInput['transmission']) ?? null,
      fuel: (v.fuel as VehicleInput['fuel']) ?? null,
      vin: v.vin.trim() || null,
      plate_no: v.plate_no.trim() || null,
      license_expiry: v.license_expiry || null,
      asking_price: v.asking_price || null,
      notes: v.notes.trim() || null,
    };
    if (this.context.can('vehicle.view_min_price')) {
      body.min_price = v.min_price || null;
    }
    this.busy.set(true);
    this.error.set(null);
    try {
      const current = this.vehicle();
      const saved = current
        ? await this.api.update(current.id, body)
        : await this.api.create({
            ...body,
            acquisition_source: 'DIRECT_PURCHASE',
            current_location_id: v.current_location_id || null,
          });
      this.visible.set(false);
      this.saved.emit(saved);
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }
}
