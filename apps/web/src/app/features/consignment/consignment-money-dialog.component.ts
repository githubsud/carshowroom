import { Component, inject, input, output } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';

import { Preview } from '../../core/api/api.models';
import { MoneyPipe } from '../../core/format/format.service';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { PostingShellComponent } from '../../shared/components/posting-shell.component';
import { positiveMoney } from '../../shared/money-input';
import { PostingDialogBase, PostingKind } from '../finance/posting-dialog.base';
import { ConsignmentService } from './consignment.service';

/** PAYOUT: pay the owner (rule 17). RECOVERY: the owner repays expenses (P-06). COLLECTION: rule 19. */
export type ConsignmentMoneyMode = 'PAYOUT' | 'RECOVERY' | 'COLLECTION';

interface MoneyBody {
  date: string;
  amount: string;
  cash_account_id: string;
  notes: string | null;
}

/** Money with a car's owner or an external showroom; defaults to the full outstanding amount. */
@Component({
  selector: 'app-consignment-money-dialog',
  imports: [ReactiveFormsModule, TranslocoPipe, InputTextModule, SelectModule, MoneyInputComponent, MoneyPipe, PostingShellComponent],
  template: `
    <app-posting-shell [visible]="visible()" [header]="'consignment.money_' + mode() | transloco" [form]="form"
                       [step]="step()" [preview]="preview()" [error]="error()" [busy]="busy()"
                       [testId]="'money-' + mode()" (review)="review()" (confirm)="confirm()" (back)="back()"
                       (dismiss)="visible.set(false)">
      <div class="dialog-fields" [formGroup]="form">
        <p class="owed">{{ 'consignment.outstanding_' + mode() | transloco }}: <strong>{{ outstanding() | money }}</strong></p>
        <div class="field">
          <label for="cm-amount">{{ 'finance.amount' | transloco }}</label>
          <app-money-input inputId="cm-amount" formControlName="amount" data-testid="amount" />
        </div>
        <div class="field">
          <label for="cm-cash">{{ (mode() === 'PAYOUT' ? 'finance.paidFrom' : 'finance.receivedIn') | transloco }}</label>
          <p-select inputId="cm-cash" formControlName="cash_account_id" [options]="accountOptions()"
                    optionLabel="label" optionValue="value" [fluid]="true" />
        </div>
        <div class="row">
          <div class="field">
            <label for="cm-date">{{ 'finance.date' | transloco }}</label>
            <input pInputText id="cm-date" type="date" formControlName="date" />
          </div>
          <div class="field">
            <label for="cm-note">{{ 'finance.note' | transloco }}</label>
            <input pInputText id="cm-note" formControlName="notes" />
          </div>
        </div>
      </div>
    </app-posting-shell>
  `,
  styles: `
    .owed {
      margin: 0;
    }
  `,
})
export class ConsignmentMoneyDialogComponent extends PostingDialogBase<MoneyBody, unknown> {
  private readonly api = inject(ConsignmentService);

  readonly mode = input.required<ConsignmentMoneyMode>();
  /** Consignment id (PAYOUT, RECOVERY) or external showroom id (COLLECTION). */
  readonly targetId = input.required<string>();
  readonly outstanding = input.required<string>();
  readonly posted = output<void>();

  readonly kind: PostingKind = 'consignment';
  readonly dateControl = 'date';
  readonly noteControl = 'notes';
  readonly form = inject(NonNullableFormBuilder).group({
    amount: ['', [Validators.required, positiveMoney]],
    cash_account_id: ['', Validators.required],
    date: ['', Validators.required],
    notes: [''],
  });

  protected reset(): void {
    this.form.reset({
      amount: this.outstanding(),
      cash_account_id: this.defaultAccountId(),
      date: this.format.todayIso(),
      notes: '',
    });
  }

  protected body(): MoneyBody {
    const v = this.form.getRawValue();
    return { date: v.date, amount: v.amount, cash_account_id: v.cash_account_id, notes: v.notes.trim() || null };
  }

  protected previewCall(body: MoneyBody): Promise<Preview> {
    if (this.mode() === 'COLLECTION') {
      return this.api.previewCollection(this.targetId(), this.collection(body));
    }
    return this.api.previewSettlement(this.targetId(), this.settlement(body));
  }

  protected postCall(body: MoneyBody, key: string): Promise<unknown> {
    if (this.mode() === 'COLLECTION') {
      return this.api.recordCollection(this.targetId(), this.collection(body), key);
    }
    return this.api.recordSettlement(this.targetId(), this.settlement(body), key);
  }

  protected emitPosted(): void {
    this.posted.emit();
  }

  private settlement(body: MoneyBody) {
    return {
      kind: this.mode() as 'PAYOUT' | 'RECOVERY',
      settle_date: body.date,
      amount: body.amount,
      cash_account_id: body.cash_account_id,
      notes: body.notes,
    };
  }

  private collection(body: MoneyBody) {
    return { collect_date: body.date, amount: body.amount, cash_account_id: body.cash_account_id, notes: body.notes };
  }
}
