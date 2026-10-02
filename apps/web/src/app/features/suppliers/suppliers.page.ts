import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';

import { CashAccount, Supplier, SupplierStatement } from '../../core/api/api.models';
import { AppDatePipe, FormatService, MoneyPipe } from '../../core/format/format.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { loaded, translationsLoaded } from '../../shared/translated';
import { FinanceService } from '../finance/finance.service';
import { PaymentDialogComponent } from '../vehicles/payment-dialog.component';
import { SuppliersService } from './suppliers.service';

const KINDS = ['WORKSHOP', 'TRANSPORT', 'PARTS', 'AD_AGENCY', 'OTHER'] as const;

/** Suppliers and workshops (D-23): what the showroom owes each, statements, payments (rule 32). */
@Component({
  selector: 'app-suppliers-page',
  imports: [
    FormsModule,
    TranslocoPipe,
    ButtonModule,
    DialogModule,
    InputTextModule,
    SelectModule,
    TableModule,
    MoneyPipe,
    AppDatePipe,
    CanDirective,
    StateComponent,
    PaymentDialogComponent,
  ],
  template: `
    <div class="page-header">
      <h1 class="page-title">{{ 'suppliers.title' | transloco }}</h1>
      <p-button icon="pi pi-plus" data-testid="add-supplier" [label]="'suppliers.add' | transloco" (onClick)="openAdd()" />
    </div>
    @if (loadError()) {
      <app-state kind="error" [message]="loadError()" (retry)="load()" />
    } @else {
      <p-table [value]="suppliers()" styleClass="p-datatable-sm" data-testid="suppliers">
        <ng-template #header>
          <tr>
            <th>{{ 'suppliers.name' | transloco }}</th>
            <th>{{ 'suppliers.kind' | transloco }}</th>
            <th>{{ 'customers.phone' | transloco }}</th>
            <th class="num">{{ 'suppliers.owed' | transloco }}</th>
            <th></th>
          </tr>
        </ng-template>
        <ng-template #body let-s>
          <tr [attr.data-testid]="'supplier-row-' + s.id">
            <td class="name">{{ s.name }}</td>
            <td>{{ 'suppliers.kind_' + s.kind | transloco }}</td>
            <td dir="ltr">{{ s.phone }}</td>
            <td class="num strong">{{ s.balance | money }}</td>
            <td class="actions-cell">
              <p-button [text]="true" size="small" [label]="'suppliers.statement' | transloco" (onClick)="openStatement(s)" />
              @if (s.balance !== '0.00') {
                <p-button *appCan="'supplier.pay'" [text]="true" size="small" [label]="'suppliers.pay' | transloco"
                          (onClick)="openPay(s)" [attr.data-testid]="'pay-' + s.id" />
              }
            </td>
          </tr>
        </ng-template>
        <ng-template #emptymessage>
          <tr><td colspan="5"><app-state kind="empty" [message]="'suppliers.none' | transloco" /></td></tr>
        </ng-template>
      </p-table>
    }

    <p-dialog [(visible)]="addOpen" [modal]="true" [header]="'suppliers.add' | transloco" [style]="{ width: 'min(420px, 96vw)' }">
      <div class="dialog-fields">
        <div class="field"><label for="s-name">{{ 'suppliers.name' | transloco }}</label>
          <input pInputText id="s-name" [(ngModel)]="draft.name" data-testid="supplier-name" /></div>
        <div class="field"><label for="s-kind">{{ 'suppliers.kind' | transloco }}</label>
          <p-select inputId="s-kind" [options]="kindOptions()" [(ngModel)]="draft.kind" optionLabel="label"
                    optionValue="value" [fluid]="true" /></div>
        <div class="field"><label for="s-phone">{{ 'customers.phone' | transloco }}</label>
          <input pInputText id="s-phone" [(ngModel)]="draft.phone" dir="ltr" inputmode="tel" /></div>
        @if (addError()) { <p class="negative">{{ addError() }}</p> }
        <p-button [label]="'settings.save' | transloco" (onClick)="add()" [disabled]="!draft.name.trim()"
                  data-testid="supplier-save" />
      </div>
    </p-dialog>

    <p-dialog [(visible)]="statementOpen" [modal]="true" [header]="statementTitle()" [style]="{ width: 'min(760px, 96vw)' }">
      @if (statement(); as st) {
        <p-table [value]="st.lines" styleClass="p-datatable-sm">
          <ng-template #header>
            <tr>
              <th>{{ 'finance.date' | transloco }}</th>
              <th>{{ 'finance.description' | transloco }}</th>
              <th class="num">{{ 'suppliers.owedMore' | transloco }}</th>
              <th class="num">{{ 'suppliers.paid' | transloco }}</th>
              <th class="num">{{ 'finance.balance' | transloco }}</th>
            </tr>
            <tr class="opening"><td colspan="4">{{ 'finance.opening' | transloco }}</td>
              <td class="num">{{ st.opening_balance | money }}</td></tr>
          </ng-template>
          <ng-template #body let-line>
            <tr [class.muted]="line.reversed || line.is_reversal">
              <td>{{ line.entry_date | appDate }}</td>
              <td>{{ line.description }}</td>
              <td class="num">{{ line.amount_owed === '0.00' ? '' : (line.amount_owed | money) }}</td>
              <td class="num">{{ line.amount_paid === '0.00' ? '' : (line.amount_paid | money) }}</td>
              <td class="num">{{ line.balance | money }}</td>
            </tr>
          </ng-template>
        </p-table>
      }
    </p-dialog>

    @if (paying(); as s) {
      <app-payment-dialog [(visible)]="payOpen" mode="supplierPayment" [targetId]="s.id" [owed]="s.balance"
                          [accounts]="accounts()" (posted)="paid()" />
    }
  `,
  styleUrl: '../vehicles/inventory.page.scss',
})
export class SuppliersPage implements OnInit {
  private readonly api = inject(SuppliersService);
  private readonly finance = inject(FinanceService);
  private readonly context = inject(TenantContextService);
  private readonly format = inject(FormatService);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  private readonly translations = translationsLoaded();

  protected readonly suppliers = signal<Supplier[]>([]);
  protected readonly accounts = signal<CashAccount[]>([]);
  protected readonly loadError = signal<string | null>(null);
  protected readonly addOpen = signal(false);
  protected readonly addError = signal<string | null>(null);
  protected readonly statementOpen = signal(false);
  protected readonly statement = signal<SupplierStatement | null>(null);
  protected readonly payOpen = signal(false);
  protected readonly paying = signal<Supplier | null>(null);
  protected draft = { name: '', kind: 'WORKSHOP' as (typeof KINDS)[number], phone: '' };

  protected readonly kindOptions = computed(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    return KINDS.map((value) => ({ value, label: this.transloco.translate(`suppliers.kind_${value}`) }));
  });
  protected readonly statementTitle = computed(
    () => `${this.transloco.translate('suppliers.statement')} — ${this.statement()?.supplier.name ?? ''}`,
  );

  ngOnInit(): void {
    void this.load();
    if (this.context.can('cash.view')) {
      void this.finance.cashAccounts().then((a) => this.accounts.set(a));
    }
  }

  protected async load(): Promise<void> {
    try {
      this.suppliers.set(await this.api.list());
      this.loadError.set(null);
    } catch (error) {
      this.loadError.set(this.errors.message(error));
    }
  }

  protected openAdd(): void {
    this.draft = { name: '', kind: 'WORKSHOP', phone: '' };
    this.addError.set(null);
    this.addOpen.set(true);
  }

  protected async add(): Promise<void> {
    try {
      await this.api.create({ name: this.draft.name.trim(), kind: this.draft.kind, phone: this.draft.phone.trim() || null });
      this.addOpen.set(false);
      await this.load();
    } catch (error) {
      this.addError.set(this.errors.message(error));
    }
  }

  protected async openStatement(supplier: Supplier): Promise<void> {
    const today = this.format.todayIso();
    try {
      this.statement.set(await this.api.statement(supplier.id, `${today.slice(0, 4)}-01-01`, today));
      this.statementOpen.set(true);
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    }
  }

  protected openPay(supplier: Supplier): void {
    this.paying.set(supplier);
    this.payOpen.set(true);
  }

  protected async paid(): Promise<void> {
    this.toast.add({ severity: 'success', summary: this.transloco.translate('finance.postedShort') });
    await this.load();
  }
}
