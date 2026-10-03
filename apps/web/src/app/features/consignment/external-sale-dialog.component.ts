import { Component, inject, input, output } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { InputTextModule } from 'primeng/inputtext';

import { ConsignmentOutPosting, ExternalSaleInput, Preview } from '../../core/api/api.models';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { PostingShellComponent } from '../../shared/components/posting-shell.component';
import { positiveMoney } from '../../shared/money-input';
import { PostingDialogBase, PostingKind } from '../finance/posting-dialog.base';
import { ConsignmentService } from './consignment.service';

/** Our car was sold by the external showroom (rule 18): price, commission by the agreement, cost of sale. */
@Component({
  selector: 'app-external-sale-dialog',
  imports: [ReactiveFormsModule, TranslocoPipe, InputTextModule, MoneyInputComponent, PostingShellComponent],
  template: `
    <app-posting-shell [visible]="visible()" [header]="'consignment.soldThere' | transloco: { name: showroomName() }"
                       [form]="form" [step]="step()" [preview]="preview()" [error]="error()" [busy]="busy()"
                       testId="external-sale-form" (review)="review()" (confirm)="confirm()" (back)="back()"
                       (dismiss)="visible.set(false)">
      <div class="dialog-fields" [formGroup]="form">
        <div class="field">
          <label for="xs-price">{{ 'vehicles.salePrice' | transloco }}</label>
          <app-money-input inputId="xs-price" formControlName="sale_price" data-testid="xs-price" />
        </div>
        <div class="row">
          <div class="field">
            <label for="xs-date">{{ 'finance.date' | transloco }}</label>
            <input pInputText id="xs-date" type="date" formControlName="sale_date" />
          </div>
          <div class="field">
            <label for="xs-buyer">{{ 'sales.buyer' | transloco }}</label>
            <input pInputText id="xs-buyer" formControlName="buyer_name" />
          </div>
        </div>
        <div class="field">
          <label for="xs-note">{{ 'finance.note' | transloco }}</label>
          <input pInputText id="xs-note" formControlName="notes" />
        </div>
      </div>
    </app-posting-shell>
  `,
})
export class ExternalSaleDialogComponent extends PostingDialogBase<ExternalSaleInput, ConsignmentOutPosting> {
  private readonly api = inject(ConsignmentService);

  readonly outId = input.required<string>();
  readonly showroomName = input.required<string>();
  readonly expectedPrice = input<string | null>(null);
  readonly posted = output<ConsignmentOutPosting>();

  readonly kind: PostingKind = 'externalSale';
  readonly dateControl = 'sale_date';
  readonly noteControl = 'notes';
  readonly form = inject(NonNullableFormBuilder).group({
    sale_price: ['', [Validators.required, positiveMoney]],
    sale_date: ['', Validators.required],
    buyer_name: [''],
    notes: [''],
  });

  protected reset(): void {
    this.form.reset({ sale_price: this.expectedPrice() ?? '', sale_date: this.format.todayIso(), buyer_name: '', notes: '' });
  }

  protected body(): ExternalSaleInput {
    const v = this.form.getRawValue();
    return {
      sale_date: v.sale_date,
      sale_price: v.sale_price,
      buyer_name: v.buyer_name.trim() || null,
      notes: v.notes.trim() || null,
    };
  }

  protected previewCall(body: ExternalSaleInput): Promise<Preview> {
    return this.api.previewExternalSale(this.outId(), body);
  }

  protected postCall(body: ExternalSaleInput, key: string): Promise<ConsignmentOutPosting> {
    return this.api.recordExternalSale(this.outId(), body, key);
  }

  protected emitPosted(result: ConsignmentOutPosting): void {
    this.posted.emit(result);
  }
}
