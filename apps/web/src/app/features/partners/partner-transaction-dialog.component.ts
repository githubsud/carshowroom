import { Component, computed, inject, input, output } from '@angular/core';
import { FormsModule, NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectModule } from 'primeng/select';

import {
  PartnerPosting,
  PartnerTransactionInput,
  PartnerTransactionKind,
  Preview,
} from '../../core/api/api.models';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { PostingPreviewComponent } from '../../shared/components/posting-preview.component';
import { positiveMoney } from '../../shared/money-input';
import { loaded, translationsLoaded } from '../../shared/translated';
import { Option, PostingDialogBase, PostingKind } from '../finance/posting-dialog.base';
import { PartnersService } from './partners.service';

const KINDS: PartnerTransactionKind[] = [
  'CONTRIBUTION',
  'DRAWING',
  'LOAN_TO_PARTNER',
  'LOAN_TO_PARTNER_REPAYMENT',
  'LOAN_FROM_PARTNER',
  'LOAN_FROM_PARTNER_REPAYMENT',
  'CAPITAL_WITHDRAWAL',
];

/** Partner money (rules 1-5, 28, 29): pick the movement, review the plain-language preview, confirm. */
@Component({
  selector: 'app-partner-transaction-dialog',
  imports: [
    FormsModule,
    ReactiveFormsModule,
    TranslocoPipe,
    ButtonModule,
    DialogModule,
    InputTextModule,
    MessageModule,
    SelectModule,
    MoneyInputComponent,
    PostingPreviewComponent,
  ],
  template: `
    <p-dialog
      [visible]="visible()"
      (visibleChange)="visible.set($event)"
      [modal]="true"
      [header]="'partners.transactionTitle' | transloco"
      [style]="{ width: 'min(480px, 96vw)' }"
      [dismissableMask]="!busy()"
    >
      @if (step() === 'form') {
        <form class="dialog-form" [formGroup]="form" (ngSubmit)="review()" data-testid="partner-txn-form">
          <div class="field">
            <label for="partner">{{ 'partners.partner' | transloco }}</label>
            <p-select inputId="partner" formControlName="partner_id" [options]="partnerOptions()"
                      optionLabel="label" optionValue="value" [fluid]="true" data-testid="txn-partner" />
          </div>
          <div class="field">
            <label for="type">{{ 'partners.movement' | transloco }}</label>
            <p-select inputId="type" formControlName="type" [options]="typeOptions()" optionLabel="label"
                      optionValue="value" [fluid]="true" data-testid="txn-type" />
          </div>
          <div class="field">
            <label for="amount">{{ 'finance.amount' | transloco }}</label>
            <app-money-input inputId="amount" formControlName="amount" data-testid="amount" />
          </div>
          <div class="field">
            <label for="cash">{{ (moneyIn() ? 'finance.receivedIn' : 'finance.paidFrom') | transloco }}</label>
            <p-select inputId="cash" formControlName="cash_account_id" [options]="accountOptions()"
                      optionLabel="label" optionValue="value" [fluid]="true" />
          </div>
          <div class="field">
            <label for="date">{{ 'finance.date' | transloco }}</label>
            <input pInputText id="date" type="date" formControlName="txn_date" />
          </div>
          <div class="field">
            <label for="notes">{{ 'finance.note' | transloco }}</label>
            <input pInputText id="notes" formControlName="notes" />
          </div>
          @if (error()) {
            <p-message severity="error" data-testid="dialog-error">{{ error() }}</p-message>
          }
          <div class="actions">
            <p-button type="button" [text]="true" [label]="'common.cancel' | transloco" (onClick)="visible.set(false)" />
            <p-button type="submit" data-testid="review" [label]="'finance.review' | transloco" [loading]="busy()" />
          </div>
        </form>
      } @else {
        @if (preview(); as p) {
          <app-posting-preview [preview]="p" />
        }
        @if (error()) {
          <p-message severity="error" data-testid="dialog-error">{{ error() }}</p-message>
        }
        <div class="actions">
          <p-button type="button" [text]="true" icon="pi pi-arrow-right" [label]="'finance.back' | transloco"
                    (onClick)="back()" [disabled]="busy()" />
          <p-button type="button" data-testid="confirm" icon="pi pi-check" [label]="'finance.confirm' | transloco"
                    [loading]="busy()" (onClick)="confirm()" />
        </div>
      }
    </p-dialog>
  `,
  styleUrl: '../finance/posting-dialog.scss',
})
export class PartnerTransactionDialogComponent extends PostingDialogBase<PartnerTransactionInput, PartnerPosting> {
  private readonly api = inject(PartnersService);
  private readonly transloco = inject(TranslocoService);
  private readonly context = inject(TenantContextService);
  private readonly translations = translationsLoaded();

  readonly presetPartnerId = input<string | null>(null);
  readonly presetType = input<PartnerTransactionKind>('CONTRIBUTION');
  readonly posted = output<PartnerPosting>();

  readonly kind: PostingKind = 'partner';
  readonly dateControl = 'txn_date';
  readonly noteControl = 'notes';
  readonly form = inject(NonNullableFormBuilder).group({
    partner_id: ['', Validators.required],
    type: ['CONTRIBUTION' as PartnerTransactionKind, Validators.required],
    amount: ['', [Validators.required, positiveMoney]],
    cash_account_id: ['', Validators.required],
    txn_date: ['', Validators.required],
    notes: [''],
  });

  protected readonly typeOptions = computed<Option[]>(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    // Taking capital out also needs the equity permission (owner).
    const allowed = KINDS.filter((k) => k !== 'CAPITAL_WITHDRAWAL' || this.context.can('partner.equity.change'));
    return allowed.map((value) => ({ value, label: this.transloco.translate(`partners.kind_${value}`) }));
  });

  protected moneyIn(): boolean {
    return ['CONTRIBUTION', 'LOAN_TO_PARTNER_REPAYMENT', 'LOAN_FROM_PARTNER'].includes(this.form.controls.type.value);
  }

  protected reset(): void {
    this.form.reset({
      partner_id: this.presetPartnerId() ?? this.partners()[0]?.id ?? '',
      type: this.presetType(),
      amount: '',
      cash_account_id: this.defaultAccountId(),
      txn_date: this.format.todayIso(),
      notes: '',
    });
  }

  protected body(): PartnerTransactionInput {
    const v = this.form.getRawValue();
    return {
      type: v.type,
      amount: v.amount,
      cash_account_id: v.cash_account_id,
      txn_date: v.txn_date,
      notes: v.notes.trim() || null,
    };
  }

  protected previewCall(body: PartnerTransactionInput): Promise<Preview> {
    return this.api.previewTransaction(this.form.controls.partner_id.value, body);
  }

  protected postCall(body: PartnerTransactionInput, key: string): Promise<PartnerPosting> {
    return this.api.recordTransaction(this.form.controls.partner_id.value, body, key);
  }

  protected emitPosted(result: PartnerPosting): void {
    this.posted.emit(result);
  }
}
