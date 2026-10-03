import { Component, computed, effect, inject, input, model, output, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';

import { ConsignmentOutRow, ExternalShowroom } from '../../core/api/api.models';
import { FormatService } from '../../core/format/format.service';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { loaded, translationsLoaded } from '../../shared/translated';
import { ConsignmentService } from './consignment.service';

/** Send one of our cars to another showroom (SPEC §4.5). No money moves until it is sold there. */
@Component({
  selector: 'app-consign-out-dialog',
  imports: [ReactiveFormsModule, TranslocoPipe, ButtonModule, DialogModule, InputTextModule, MessageModule, SelectModule,
            SelectButtonModule, MoneyInputComponent],
  template: `
    <p-dialog [visible]="visible()" (visibleChange)="visible.set($event)" [modal]="true"
              [header]="'consignment.sendOut' | transloco" [style]="{ width: 'min(480px, 96vw)' }">
      <form class="dialog-fields" [formGroup]="form" (ngSubmit)="save()" data-testid="consign-out-form">
        <div class="field">
          <label for="co-showroom">{{ 'consignment.showroom' | transloco }}</label>
          <p-select inputId="co-showroom" formControlName="external_showroom_id" [options]="showroomOptions()"
                    optionLabel="label" optionValue="value" [fluid]="true" data-testid="co-showroom" />
        </div>
        <div class="field">
          <span class="label">{{ 'consignment.theirCommission' | transloco }}</span>
          <p-selectbutton formControlName="commission_type" [options]="typeOptions()" optionLabel="label"
                          optionValue="value" [allowEmpty]="false" />
        </div>
        <div class="row">
          <div class="field">
            <label for="co-value">{{ 'consignment.commissionValue' | transloco }}</label>
            <app-money-input inputId="co-value" formControlName="commission_value" data-testid="co-value" />
          </div>
          <div class="field">
            <label for="co-expected">{{ 'consignment.expectedPrice' | transloco }}</label>
            <app-money-input inputId="co-expected" formControlName="expected_price" />
          </div>
        </div>
        <div class="field">
          <label for="co-date">{{ 'finance.date' | transloco }}</label>
          <input pInputText id="co-date" type="date" formControlName="sent_date" />
        </div>
        @if (error()) {
          <p-message severity="error" data-testid="dialog-error">{{ error() }}</p-message>
        }
        <div class="actions">
          <p-button type="button" [text]="true" [label]="'common.cancel' | transloco" (onClick)="visible.set(false)" />
          <p-button type="submit" [label]="'consignment.sendOut' | transloco" [loading]="busy()" data-testid="co-save" />
        </div>
      </form>
    </p-dialog>
  `,
  styles: `
    .label {
      font-size: 0.875rem;
    }
    .actions {
      display: flex;
      gap: var(--space-2);
      justify-content: flex-end;
    }
  `,
})
export class ConsignOutDialogComponent {
  private readonly api = inject(ConsignmentService);
  private readonly errors = inject(ErrorMessageService);
  private readonly format = inject(FormatService);
  private readonly transloco = inject(TranslocoService);
  private readonly translations = translationsLoaded();

  readonly visible = model(false);
  readonly vehicleId = input.required<string>();
  readonly saved = output<ConsignmentOutRow>();

  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly showrooms = signal<ExternalShowroom[]>([]);
  protected readonly showroomOptions = computed(() => this.showrooms().map((s) => ({ value: s.id, label: s.name })));
  protected readonly typeOptions = computed(() =>
    loaded(this.translations())
      ? (['FIXED', 'PCT'] as const).map((value) => ({ value, label: this.transloco.translate(`consignment.commission_${value}`) }))
      : [],
  );
  protected readonly form = inject(NonNullableFormBuilder).group({
    external_showroom_id: ['', Validators.required],
    commission_type: ['FIXED' as 'FIXED' | 'PCT'],
    commission_value: ['0', Validators.required],
    expected_price: [''],
    sent_date: ['', Validators.required],
  });

  constructor() {
    effect(() => {
      if (this.visible()) {
        this.error.set(null);
        this.form.reset({ sent_date: this.format.todayIso(), commission_type: 'FIXED', commission_value: '0' });
        void this.api.showrooms().then((list) => {
          this.showrooms.set(list);
          if (list.length === 1) {
            this.form.patchValue({ external_showroom_id: list[0].id });
          }
        });
      }
    });
  }

  protected async save(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const v = this.form.getRawValue();
    this.busy.set(true);
    this.error.set(null);
    try {
      const row = await this.api.consignOut({
        vehicle_id: this.vehicleId(),
        external_showroom_id: v.external_showroom_id,
        sent_date: v.sent_date,
        commission_type: v.commission_type,
        commission_value: v.commission_value || '0',
        expected_price: v.expected_price || null,
        notes: null,
      });
      this.visible.set(false);
      this.saved.emit(row);
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }
}
