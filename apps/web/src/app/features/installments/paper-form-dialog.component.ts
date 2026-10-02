import { Component, computed, effect, inject, input, model, output, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectButtonModule } from 'primeng/selectbutton';
import { SelectModule } from 'primeng/select';

import { InstallmentPlan, Paper } from '../../core/api/api.models';
import { FormatService } from '../../core/format/format.service';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { positiveMoney } from '../../shared/money-input';
import { InstallmentsService } from './installments.service';

/** Register a promissory note or post-dated cheque for an installment (SPEC §4.8). */
@Component({
  selector: 'app-paper-form-dialog',
  imports: [ReactiveFormsModule, TranslocoPipe, ButtonModule, DialogModule, InputTextModule, MessageModule, SelectButtonModule, SelectModule, MoneyInputComponent],
  template: `
    <p-dialog [visible]="visible()" (visibleChange)="visible.set($event)" [modal]="true"
              [header]="'papers.add' | transloco" [style]="{ width: 'min(520px, 96vw)' }">
      <form class="dialog-fields" [formGroup]="form" (ngSubmit)="save()" data-testid="paper-form">
        <p-selectbutton formControlName="paper_type" [options]="types" optionValue="value" [allowEmpty]="false">
          <ng-template #item let-option>{{ option.key | transloco }}</ng-template>
        </p-selectbutton>
        <div class="row">
          <div class="field">
            <label for="pf-number">{{ 'papers.number' | transloco }}</label>
            <input pInputText id="pf-number" formControlName="number" dir="ltr" data-testid="paper-number" />
          </div>
          <div class="field">
            <label for="pf-installment">{{ 'installments.installment' | transloco }}</label>
            <p-select inputId="pf-installment" formControlName="installment_id" [options]="installmentOptions()"
                      optionLabel="label" optionValue="value" [fluid]="true" (onChange)="pickInstallment($event.value)" />
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label for="pf-amount">{{ 'finance.amount' | transloco }}</label>
            <app-money-input inputId="pf-amount" formControlName="amount" data-testid="paper-amount" />
          </div>
          <div class="field">
            <label for="pf-due">{{ 'papers.dueDate' | transloco }}</label>
            <input pInputText id="pf-due" type="date" formControlName="due_date" />
          </div>
        </div>
        @if (values().paper_type === 'PDC') {
          <div class="row">
            <div class="field">
              <label for="pf-bank">{{ 'papers.drawerBank' | transloco }}</label>
              <input pInputText id="pf-bank" formControlName="drawer_bank" />
            </div>
            <div class="field">
              <label for="pf-branch">{{ 'papers.drawerBranch' | transloco }}</label>
              <input pInputText id="pf-branch" formControlName="drawer_branch" />
            </div>
          </div>
          <div class="field">
            <label for="pf-holder">{{ 'papers.accountHolder' | transloco }}</label>
            <input pInputText id="pf-holder" formControlName="account_holder" />
          </div>
        }
        <div class="field">
          <label for="pf-location">{{ 'papers.storageLocation' | transloco }}</label>
          <input pInputText id="pf-location" formControlName="storage_location" />
        </div>
        @if (error()) {
          <p-message severity="error" data-testid="dialog-error">{{ error() }}</p-message>
        }
        <div class="actions">
          <p-button type="button" [text]="true" [label]="'common.cancel' | transloco" (onClick)="visible.set(false)" />
          <p-button type="submit" [label]="'settings.save' | transloco" [loading]="busy()" data-testid="paper-save" />
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
export class PaperFormDialogComponent {
  private readonly api = inject(InstallmentsService);
  private readonly errors = inject(ErrorMessageService);
  private readonly format = inject(FormatService);

  readonly visible = model(false);
  readonly plan = input.required<InstallmentPlan>();
  readonly saved = output<Paper>();

  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly types = [
    { value: 'PDC', key: 'papers.type_PDC' },
    { value: 'PROMISSORY_NOTE', key: 'papers.type_PROMISSORY_NOTE' },
  ];
  protected readonly form = inject(NonNullableFormBuilder).group({
    paper_type: ['PDC' as 'PDC' | 'PROMISSORY_NOTE'],
    number: ['', Validators.required],
    installment_id: [''],
    amount: ['', [Validators.required, positiveMoney]],
    due_date: ['', Validators.required],
    drawer_bank: [''],
    drawer_branch: [''],
    account_holder: [''],
    storage_location: [''],
  });
  protected readonly values = toSignal(this.form.valueChanges, { initialValue: this.form.getRawValue() });
  protected readonly installmentOptions = computed(() =>
    this.plan()
      .installments.filter((i) => i.state !== 'PAID' && i.state !== 'CANCELLED')
      .map((i) => ({ value: i.id, label: `#${i.seq} — ${this.format.date(i.due_date)} — ${this.format.money(i.remaining)}` })),
  );

  constructor() {
    effect(() => {
      if (this.visible()) {
        const next = this.plan().installments.find((i) => i.state !== 'PAID' && i.state !== 'CANCELLED');
        this.error.set(null);
        this.form.reset({
          paper_type: 'PDC',
          number: '',
          installment_id: next?.id ?? '',
          amount: next?.remaining ?? '',
          due_date: next?.due_date ?? this.format.todayIso(),
          drawer_bank: '',
          drawer_branch: '',
          account_holder: this.plan().customer_name,
          storage_location: '',
        });
      }
    });
  }

  protected pickInstallment(id: string): void {
    const installment = this.plan().installments.find((i) => i.id === id);
    if (installment) {
      this.form.patchValue({ amount: installment.remaining, due_date: installment.due_date });
    }
  }

  protected async save(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const v = this.form.getRawValue();
    const pdc = v.paper_type === 'PDC';
    this.busy.set(true);
    this.error.set(null);
    try {
      const paper = await this.api.createPaper({
        paper_type: v.paper_type,
        number: v.number.trim(),
        customer_id: this.plan().customer_id,
        installment_id: v.installment_id || null,
        amount: v.amount,
        due_date: v.due_date,
        issue_date: this.format.todayIso(),
        drawer_bank: pdc ? v.drawer_bank.trim() || null : null,
        drawer_branch: pdc ? v.drawer_branch.trim() || null : null,
        account_holder: pdc ? v.account_holder.trim() || null : null,
        storage_location: v.storage_location.trim() || null,
      });
      this.visible.set(false);
      this.saved.emit(paper);
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }
}
