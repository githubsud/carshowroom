import { Component, computed, inject, input, output } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';

import { Preview, ReservationPosting, ReservationSettleInput } from '../../core/api/api.models';
import { MoneyPipe } from '../../core/format/format.service';
import { PostingShellComponent } from '../../shared/components/posting-shell.component';
import { loaded, translationsLoaded } from '../../shared/translated';
import { Option, PostingDialogBase, PostingKind } from '../finance/posting-dialog.base';
import { SalesService } from './sales.service';

/** Settle a deposit: refund it (rule 34) or keep it as other income (rule 35). */
@Component({
  selector: 'app-settle-dialog',
  imports: [ReactiveFormsModule, TranslocoPipe, InputTextModule, SelectModule, SelectButtonModule, MoneyPipe, PostingShellComponent],
  template: `
    <app-posting-shell [visible]="visible()" [header]="'sales.settleTitle' | transloco" [form]="form" [step]="step()"
                       [preview]="preview()" [error]="error()" [busy]="busy()" testId="settle-form"
                       (review)="review()" (confirm)="confirm()" (back)="back()" (dismiss)="visible.set(false)">
      <div class="dialog-fields" [formGroup]="form">
        <p>{{ 'sales.deposit' | transloco }}: <strong>{{ amount() | money }}</strong></p>
        <p-selectbutton formControlName="action" [options]="actions()" optionLabel="label" optionValue="value"
                        [allowEmpty]="false" data-testid="settle-action" />
        @if (action() === 'REFUND') {
          <div class="field">
            <label for="s-cash">{{ 'finance.paidFrom' | transloco }}</label>
            <p-select inputId="s-cash" formControlName="cash_account_id" [options]="accountOptions()"
                      optionLabel="label" optionValue="value" [fluid]="true" />
          </div>
        }
        <div class="field">
          <label for="s-date">{{ 'finance.date' | transloco }}</label>
          <input pInputText id="s-date" type="date" formControlName="settle_date" />
        </div>
      </div>
    </app-posting-shell>
  `,
})
export class SettleDialogComponent extends PostingDialogBase<ReservationSettleInput, ReservationPosting> {
  private readonly api = inject(SalesService);
  private readonly transloco = inject(TranslocoService);
  private readonly translations = translationsLoaded();

  readonly reservationId = input.required<string>();
  readonly amount = input.required<string>();
  readonly posted = output<ReservationPosting>();

  readonly kind: PostingKind = 'settle';
  readonly dateControl = 'settle_date';
  readonly noteControl = 'settle_date';
  readonly form = inject(NonNullableFormBuilder).group({
    action: ['REFUND' as 'REFUND' | 'FORFEIT', Validators.required],
    cash_account_id: [''],
    settle_date: ['', Validators.required],
  });

  private readonly values = toSignal(this.form.valueChanges, { initialValue: this.form.getRawValue() });
  protected readonly action = computed(() => this.values().action);
  protected readonly actions = computed<Option[]>(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    return [
      { value: 'REFUND', label: this.transloco.translate('sales.refund') },
      { value: 'FORFEIT', label: this.transloco.translate('sales.forfeit') },
    ];
  });

  protected reset(): void {
    this.form.reset({ action: 'REFUND', cash_account_id: this.defaultAccountId(), settle_date: this.format.todayIso() });
  }

  protected body(): ReservationSettleInput {
    const v = this.form.getRawValue();
    return {
      action: v.action,
      settle_date: v.settle_date,
      cash_account_id: v.action === 'REFUND' ? v.cash_account_id : null,
    };
  }

  protected previewCall(body: ReservationSettleInput): Promise<Preview> {
    return this.api.previewSettle(this.reservationId(), body);
  }

  protected postCall(body: ReservationSettleInput, key: string): Promise<ReservationPosting> {
    return this.api.settle(this.reservationId(), body, key);
  }

  protected emitPosted(result: ReservationPosting): void {
    this.posted.emit(result);
  }
}
