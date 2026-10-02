import { Component, computed, inject, input, output } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { CheckboxModule } from 'primeng/checkbox';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';

import { Paper, PaperAction, PaperActionInput, PaperPosting, Preview } from '../../core/api/api.models';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { PostingShellComponent } from '../../shared/components/posting-shell.component';
import { loaded, translationsLoaded } from '../../shared/translated';
import { Option, PostingDialogBase, PostingKind } from '../finance/posting-dialog.base';
import { InstallmentsService } from './installments.service';

/** What each status can become next (mirrors private.paper_transition_allowed). */
export function nextActions(paper: Pick<Paper, 'paper_type' | 'status'>): PaperAction[] {
  if (paper.paper_type === 'PDC') {
    const map: Partial<Record<Paper['status'], PaperAction[]>> = {
      HELD: ['DEPOSIT', 'COLLECT', 'RETURN', 'DEFAULT'],
      DEPOSITED: ['COLLECT', 'BOUNCE'],
      COLLECTED: ['BOUNCE'],
      BOUNCED: ['DEPOSIT', 'LEGAL', 'RETURN'],
      DEFAULTED: ['LEGAL', 'RETURN'],
      LEGAL: ['RETURN'],
    };
    return map[paper.status] ?? [];
  }
  const notes: Partial<Record<Paper['status'], PaperAction[]>> = {
    HELD: ['RETURN', 'DEFAULT'],
    DEFAULTED: ['LEGAL', 'RETURN'],
    LEGAL: ['RETURN'],
  };
  return notes[paper.status] ?? [];
}

/**
 * Move a paper through its life (SPEC §4.8): deposit, collect (posts the
 * receipt, A-10), bounce (rule 27 if it was collected, with optional bank
 * charges, P-07), return, default, legal process.
 */
@Component({
  selector: 'app-paper-action-dialog',
  imports: [ReactiveFormsModule, TranslocoPipe, CheckboxModule, InputTextModule, SelectModule, MoneyInputComponent, PostingShellComponent],
  template: `
    <app-posting-shell [visible]="visible()" [header]="('papers.actionTitle' | transloco) + ' ' + paper().number"
                       [form]="form" [step]="step()" [preview]="preview()" [error]="error()" [busy]="busy()"
                       testId="paper-action-form" (review)="review()" (confirm)="confirm()" (back)="back()"
                       (dismiss)="visible.set(false)">
      <div class="dialog-fields" [formGroup]="form">
        <div class="field">
          <label for="pa-action">{{ 'papers.action' | transloco }}</label>
          <p-select inputId="pa-action" formControlName="action" [options]="actionOptions()" optionLabel="label"
                    optionValue="value" [fluid]="true" data-testid="paper-action" />
        </div>
        @if (action() === 'COLLECT') {
          <div class="field">
            <label for="pa-cash">{{ 'finance.receivedIn' | transloco }}</label>
            <p-select inputId="pa-cash" formControlName="cash_account_id" [options]="accountOptions()" optionLabel="label"
                      optionValue="value" [fluid]="true" data-testid="paper-cash" />
          </div>
        }
        @if (action() === 'BOUNCE' && paper().status === 'COLLECTED') {
          <div class="field">
            <label for="pa-charges">{{ 'papers.bankCharges' | transloco }}</label>
            <app-money-input inputId="pa-charges" formControlName="bank_charges" />
          </div>
          <div class="check">
            <p-checkbox formControlName="charge_customer" [binary]="true" inputId="pa-recharge" />
            <label for="pa-recharge">{{ 'papers.chargeCustomer' | transloco }}</label>
          </div>
        }
        <div class="field">
          <label for="pa-date">{{ 'finance.date' | transloco }}</label>
          <input pInputText id="pa-date" type="date" formControlName="action_date" />
        </div>
        <div class="field">
          <label for="pa-note">{{ 'finance.note' | transloco }}</label>
          <input pInputText id="pa-note" formControlName="note" />
        </div>
      </div>
    </app-posting-shell>
  `,
  styles: `
    .check {
      display: flex;
      gap: var(--space-2);
      align-items: center;
    }
  `,
})
export class PaperActionDialogComponent extends PostingDialogBase<PaperActionInput, PaperPosting> {
  private readonly api = inject(InstallmentsService);
  private readonly transloco = inject(TranslocoService);
  private readonly translations = translationsLoaded();

  readonly paper = input.required<Paper>();
  readonly posted = output<PaperPosting>();

  readonly kind: PostingKind = 'paperAction';
  readonly dateControl = 'action_date';
  readonly noteControl = 'note';
  readonly form = inject(NonNullableFormBuilder).group({
    action: ['' as PaperAction | '', Validators.required],
    cash_account_id: [''],
    bank_charges: [''],
    charge_customer: [false],
    action_date: ['', Validators.required],
    note: [''],
  });
  private readonly values = toSignal(this.form.valueChanges, { initialValue: this.form.getRawValue() });
  protected readonly action = computed(() => this.values().action);
  protected readonly actionOptions = computed<Option[]>(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    return nextActions(this.paper()).map((value) => ({ value, label: this.transloco.translate(`papers.action_${value}`) }));
  });

  protected reset(): void {
    this.form.reset({
      action: nextActions(this.paper())[0] ?? '',
      cash_account_id: this.accounts().find((a) => a.kind === 'BANK')?.id ?? this.defaultAccountId(),
      bank_charges: '',
      charge_customer: false,
      action_date: this.format.todayIso(),
      note: '',
    });
  }

  protected body(): PaperActionInput {
    const v = this.form.getRawValue();
    return {
      action: v.action as PaperAction,
      action_date: v.action_date,
      cash_account_id: v.action === 'COLLECT' ? v.cash_account_id : null,
      bank_charges: v.action === 'BOUNCE' && v.bank_charges ? v.bank_charges : null,
      charge_customer: v.charge_customer,
      note: v.note.trim() || null,
    };
  }

  protected previewCall(body: PaperActionInput): Promise<Preview> {
    return this.api.previewPaperAction(this.paper().id, body);
  }

  protected postCall(body: PaperActionInput, key: string): Promise<PaperPosting> {
    return this.api.paperAction(this.paper().id, body, key);
  }

  protected emitPosted(result: PaperPosting): void {
    this.posted.emit(result);
  }
}
