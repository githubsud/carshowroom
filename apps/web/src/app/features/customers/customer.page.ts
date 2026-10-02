import { Component, inject, input, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { TagModule } from 'primeng/tag';

import { CashAccount, CustomerDetail, InstallmentStatement } from '../../core/api/api.models';
import { MoneyPipe } from '../../core/format/format.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { LanguageService } from '../../core/i18n/language.service';
import { FinanceService } from '../finance/finance.service';
import { InstallmentsService } from '../installments/installments.service';
import { PaymentDialogComponent } from '../vehicles/payment-dialog.component';
import { CustomersService } from './customers.service';

/** One customer: contact, flags, and the money the showroom holds for or owes them. */
@Component({
  selector: 'app-customer-page',
  imports: [
    FormsModule,
    RouterLink,
    TranslocoPipe,
    ButtonModule,
    DialogModule,
    InputTextModule,
    TagModule,
    MoneyPipe,
    CanDirective,
    StateComponent,
    PaymentDialogComponent,
  ],
  template: `
    <a class="back" [routerLink]="['/t', context.activeTenantId(), 'customers']">← {{ 'customers.title' | transloco }}</a>
    @if (loadError()) {
      <app-state kind="error" [message]="loadError()" (retry)="load()" />
    } @else if (detail(); as d) {
      <div class="page-header">
        <div>
          <h1 class="page-title" data-testid="customer-title">{{ d.customer.name }}</h1>
          <div class="meta">
            <span dir="ltr">{{ d.customer.phone_primary }}</span>
            @for (phone of d.customer.phones; track phone) { <span dir="ltr">{{ phone }}</span> }
            @if (d.customer.is_buyer) { <p-tag severity="info" [value]="'customers.buyer' | transloco" /> }
            @if (d.customer.is_seller) { <p-tag severity="secondary" [value]="'customers.seller' | transloco" /> }
          </div>
        </div>
        <p-button *appCan="'customer.manage'" icon="pi pi-pencil" [text]="true" [label]="'vehicles.edit' | transloco"
                  (onClick)="openEdit()" />
      </div>
      @if (d.customer.national_id_masked) {
        <p>
          {{ 'customers.nationalId' | transloco }}: <span dir="ltr">{{ nationalId() ?? d.customer.national_id_masked }}</span>
          @if (!nationalId()) {
            <p-button *appCan="'customer.view_national_id'" [text]="true" size="small"
                      [label]="'partners.reveal' | transloco" (onClick)="reveal()" />
          }
        </p>
      }
      @if (d.customer.address) { <p>{{ d.customer.address }}</p> }
      @if (d.customer.notes) { <p class="sub">{{ d.customer.notes }}</p> }

      @if (d.balances; as b) {
        <section class="card">
          <h2>{{ 'customers.money' | transloco }}</h2>
          <div class="figures">
            <div class="figure"><span>{{ 'customers.depositsHeld' | transloco }}</span><strong>{{ b.deposits_held | money }}</strong></div>
            <div class="figure"><span>{{ 'customers.creditOwed' | transloco }}</span>
              <strong data-testid="credit-owed">{{ b.credit_owed | money }}</strong></div>
          </div>
          @if (b.credit_owed !== '0.00') {
            <p-button *appCan="'cash.transact'" icon="pi pi-replay" [label]="'customers.refund' | transloco"
                      (onClick)="refundOpen.set(true)" data-testid="refund" />
          }
        </section>
        <app-payment-dialog [(visible)]="refundOpen" mode="refund" [targetId]="d.customer.id" [owed]="b.credit_owed"
                            [accounts]="accounts()" (posted)="paid()" />
      }
      @if (d.seller_payables?.length) {
        <section class="card">
          <h2>{{ 'customers.owedToThem' | transloco }}</h2>
          <ul>
            @for (p of d.seller_payables; track p.vehicle_id) {
              <li><a [routerLink]="['/t', context.activeTenantId(), 'vehicles', p.vehicle_id]">{{ p.vehicle_label }}
                ({{ p.stock_no }})</a> — {{ p.outstanding | money }}</li>
            }
          </ul>
        </section>
      }

      @if (statement(); as st) {
        @if (st.plans.length) {
          <section class="card" data-testid="installment-statement">
            <h2>{{ 'installments.customerStatement' | transloco }}</h2>
            <div class="figures">
              <div class="figure"><span>{{ 'installments.financed' | transloco }}</span><strong>{{ st.total_financed | money }}</strong></div>
              <div class="figure"><span>{{ 'installments.paid' | transloco }}</span><strong>{{ st.total_paid | money }}</strong></div>
              <div class="figure"><span>{{ 'installments.remaining' | transloco }}</span><strong>{{ st.total_remaining | money }}</strong></div>
              <div class="figure negative"><span>{{ 'installments.overdue' | transloco }}</span><strong>{{ st.total_overdue | money }}</strong></div>
            </div>
            <ul>
              @for (plan of st.plans; track plan.id) {
                <li><a [routerLink]="['/t', context.activeTenantId(), 'installments', 'plans', plan.id]">{{ plan.sale_no }} —
                  {{ plan.vehicle_label }}</a> — {{ plan.remaining_total | money }}
                  @if (plan.status === 'CANCELLED') { <p-tag severity="danger" [value]="'sales.status_CANCELLED' | transloco" /> }</li>
              }
            </ul>
            <p-button icon="pi pi-file-pdf" [outlined]="true" label="PDF" (onClick)="downloadStatement()" />
          </section>
        }
      }

      <p-dialog [(visible)]="editOpen" [modal]="true" [header]="'vehicles.edit' | transloco" [style]="{ width: 'min(440px, 96vw)' }">
        <div class="dialog-fields">
          <div class="field"><label for="e-name">{{ 'customers.name' | transloco }}</label>
            <input pInputText id="e-name" [(ngModel)]="edit.name" /></div>
          <div class="field"><label for="e-phone">{{ 'customers.phone' | transloco }}</label>
            <input pInputText id="e-phone" [(ngModel)]="edit.phone" dir="ltr" inputmode="tel" /></div>
          <div class="field"><label for="e-address">{{ 'customers.address' | transloco }}</label>
            <input pInputText id="e-address" [(ngModel)]="edit.address" /></div>
          <div class="field"><label for="e-notes">{{ 'finance.note' | transloco }}</label>
            <input pInputText id="e-notes" [(ngModel)]="edit.notes" /></div>
          <p-button [label]="'settings.save' | transloco" (onClick)="save()" [disabled]="!edit.name.trim()" />
        </div>
      </p-dialog>
    } @else {
      <app-state kind="loading" />
    }
  `,
  styleUrl: '../vehicles/vehicle-file.page.scss',
})
export class CustomerPage implements OnInit {
  private readonly api = inject(CustomersService);
  private readonly finance = inject(FinanceService);
  private readonly installments = inject(InstallmentsService);
  private readonly language = inject(LanguageService);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  protected readonly context = inject(TenantContextService);

  readonly customerId = input.required<string>();

  protected readonly detail = signal<CustomerDetail | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly accounts = signal<CashAccount[]>([]);
  protected readonly nationalId = signal<string | null>(null);
  protected readonly statement = signal<InstallmentStatement | null>(null);
  protected readonly refundOpen = signal(false);
  protected readonly editOpen = signal(false);
  protected edit = { name: '', phone: '', address: '', notes: '' };

  ngOnInit(): void {
    void this.load();
    if (this.context.can('installment.view')) {
      void this.installments.statement(this.customerId()).then((s) => this.statement.set(s)).catch(() => undefined);
    }
    if (this.context.can('cash.view')) {
      void this.finance.cashAccounts().then((a) => this.accounts.set(a));
    }
  }

  protected async load(): Promise<void> {
    try {
      this.detail.set(await this.api.get(this.customerId()));
      this.loadError.set(null);
    } catch (error) {
      this.loadError.set(this.errors.message(error));
    }
  }

  protected async reveal(): Promise<void> {
    try {
      this.nationalId.set((await this.api.nationalId(this.customerId())).national_id);
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    }
  }

  protected openEdit(): void {
    const c = this.detail()?.customer;
    this.edit = { name: c?.name ?? '', phone: c?.phone_primary ?? '', address: c?.address ?? '', notes: c?.notes ?? '' };
    this.editOpen.set(true);
  }

  protected async save(): Promise<void> {
    try {
      await this.api.update(this.customerId(), {
        name: this.edit.name.trim(),
        phone: this.edit.phone.trim() || null,
        address: this.edit.address.trim() || null,
        notes: this.edit.notes.trim() || null,
      });
      this.editOpen.set(false);
      await this.load();
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    }
  }

  protected async downloadStatement(): Promise<void> {
    try {
      const blob = await this.installments.statementPdf(this.customerId(), this.language.language());
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `installments-${this.customerId()}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    }
  }

  protected async paid(): Promise<void> {
    this.toast.add({ severity: 'success', summary: this.transloco.translate('finance.postedShort') });
    await this.load();
  }
}
