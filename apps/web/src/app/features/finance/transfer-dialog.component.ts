import { Component, inject, output } from '@angular/core';
import {
  AbstractControl,
  FormsModule,
  NonNullableFormBuilder,
  ReactiveFormsModule,
  ValidationErrors,
  Validators,
} from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';

import { Preview, TransferInput, TransferPosting } from '../../core/api/api.models';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { PostingPreviewComponent } from '../../shared/components/posting-preview.component';
import { positiveMoney } from '../../shared/money-input';
import { FinanceService } from './finance.service';
import { PostingDialogBase, PostingKind } from './posting-dialog.base';

function differentAccounts(group: AbstractControl): ValidationErrors | null {
  const from = group.get('from_cash_account_id')?.value;
  const to = group.get('to_cash_account_id')?.value;
  return from && to && from === to ? { sameAccount: true } : null;
}

/** Move money between a cash box and a bank account (rule 21). */
@Component({
  selector: 'app-transfer-dialog',
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
export class TransferDialogComponent extends PostingDialogBase<TransferInput, TransferPosting> {
  private readonly finance = inject(FinanceService);
  readonly posted = output<TransferPosting>();

  readonly kind: PostingKind = 'transfer';
  readonly dateControl = 'transfer_date';
  readonly noteControl = 'notes';
  readonly form = inject(NonNullableFormBuilder).group(
    {
      transfer_date: ['', Validators.required],
      from_cash_account_id: ['', Validators.required],
      to_cash_account_id: ['', Validators.required],
      amount: ['', [Validators.required, positiveMoney]],
      notes: [''],
    },
    { validators: differentAccounts },
  );

  protected reset(): void {
    const cashBox = this.accounts().find((a) => a.kind === 'CASH_BOX');
    const bank = this.accounts().find((a) => a.kind === 'BANK');
    this.form.reset({
      transfer_date: this.format.todayIso(),
      from_cash_account_id: cashBox?.id ?? '',
      to_cash_account_id: bank?.id ?? '',
      amount: '',
      notes: '',
    });
  }

  protected body(): TransferInput {
    const v = this.form.getRawValue();
    return { ...v, notes: v.notes.trim() || null };
  }

  protected previewCall(body: TransferInput): Promise<Preview> {
    return this.finance.previewTransfer(body);
  }

  protected postCall(body: TransferInput, key: string): Promise<TransferPosting> {
    return this.finance.recordTransfer(body, key);
  }

  protected emitPosted(result: TransferPosting): void {
    this.posted.emit(result);
  }
}
