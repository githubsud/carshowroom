import { Component, inject, input, output } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { InputTextModule } from 'primeng/inputtext';

import { Preview, SaleCancelInput, SalePosting } from '../../core/api/api.models';
import { PostingShellComponent } from '../../shared/components/posting-shell.component';
import { PostingDialogBase, PostingKind } from '../finance/posting-dialog.base';
import { SalesService } from './sales.service';

/** Cancel a posted sale (SPEC §4.7): reason required; the preview says what happens to the money (D-41). */
@Component({
  selector: 'app-cancel-sale-dialog',
  imports: [ReactiveFormsModule, TranslocoPipe, InputTextModule, PostingShellComponent],
  template: `
    <app-posting-shell [visible]="visible()" [header]="'sales.cancelTitle' | transloco" [form]="form" [step]="step()"
                       [preview]="preview()" [error]="error()" [busy]="busy()" testId="cancel-form"
                       (review)="review()" (confirm)="confirm()" (back)="back()" (dismiss)="visible.set(false)">
      <div class="dialog-fields" [formGroup]="form">
        <div class="field">
          <label for="c-reason">{{ 'sales.cancelReason' | transloco }}</label>
          <input pInputText id="c-reason" formControlName="reason" data-testid="cancel-reason" />
        </div>
        <div class="field">
          <label for="c-date">{{ 'finance.date' | transloco }}</label>
          <input pInputText id="c-date" type="date" formControlName="cancel_date" />
        </div>
      </div>
    </app-posting-shell>
  `,
})
export class CancelSaleDialogComponent extends PostingDialogBase<SaleCancelInput, SalePosting> {
  private readonly api = inject(SalesService);

  readonly saleId = input.required<string>();
  readonly posted = output<SalePosting>();

  readonly kind: PostingKind = 'cancelSale';
  readonly dateControl = 'cancel_date';
  readonly noteControl = 'reason';
  readonly form = inject(NonNullableFormBuilder).group({
    reason: ['', [Validators.required, Validators.minLength(3)]],
    cancel_date: ['', Validators.required],
  });

  protected reset(): void {
    this.form.reset({ reason: '', cancel_date: this.format.todayIso() });
  }

  protected body(): SaleCancelInput {
    const v = this.form.getRawValue();
    return { reason: v.reason.trim(), cancel_date: v.cancel_date };
  }

  protected previewCall(body: SaleCancelInput): Promise<Preview> {
    return this.api.previewCancel(this.saleId(), body);
  }

  protected postCall(body: SaleCancelInput, key: string): Promise<SalePosting> {
    return this.api.cancel(this.saleId(), body, key);
  }

  protected emitPosted(result: SalePosting): void {
    this.posted.emit(result);
  }
}
