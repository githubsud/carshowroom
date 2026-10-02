import { Component, inject, output } from '@angular/core';
import { FormsModule, NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';

import { OtherIncomeInput, OtherIncomePosting, Preview } from '../../core/api/api.models';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { PostingPreviewComponent } from '../../shared/components/posting-preview.component';
import { positiveMoney } from '../../shared/money-input';
import { FinanceService } from './finance.service';
import { PostingDialogBase, PostingKind } from './posting-dialog.base';

/** Record other income (P-01): money in, credited to 4900 other income. */
@Component({
  selector: 'app-income-dialog',
  imports: [
    FormsModule,
    ReactiveFormsModule,
    TranslocoPipe,
    ButtonModule,
    DialogModule,
    InputTextModule,
    MessageModule,
    SelectModule,
    SelectButtonModule,
    MoneyInputComponent,
    PostingPreviewComponent,
  ],
  templateUrl: './posting-dialog.html',
  styleUrl: './posting-dialog.scss',
})
export class IncomeDialogComponent extends PostingDialogBase<OtherIncomeInput, OtherIncomePosting> {
  private readonly finance = inject(FinanceService);
  readonly posted = output<OtherIncomePosting>();

  readonly kind: PostingKind = 'income';
  readonly dateControl = 'income_date';
  readonly noteControl = 'description';
  readonly form = inject(NonNullableFormBuilder).group({
    income_date: ['', Validators.required],
    amount: ['', [Validators.required, positiveMoney]],
    cash_account_id: ['', Validators.required],
    description: ['', Validators.required],
  });

  protected reset(): void {
    this.form.reset({
      income_date: this.format.todayIso(),
      amount: '',
      cash_account_id: this.defaultAccountId(),
      description: '',
    });
  }

  protected body(): OtherIncomeInput {
    const v = this.form.getRawValue();
    return { ...v, description: v.description.trim() };
  }

  protected previewCall(body: OtherIncomeInput): Promise<Preview> {
    return this.finance.previewIncome(body);
  }

  protected postCall(body: OtherIncomeInput, key: string): Promise<OtherIncomePosting> {
    return this.finance.recordIncome(body, key);
  }

  protected emitPosted(result: OtherIncomePosting): void {
    this.posted.emit(result);
  }
}
