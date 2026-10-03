import { Component, inject, input, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { TagModule } from 'primeng/tag';

import { CashAccount, Consignment } from '../../core/api/api.models';
import { AppDatePipe, FormatService, MoneyPipe } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { saveBlob } from '../../shared/download';
import { ErrorMessageService } from '../../shared/error-message.service';
import { FinanceService } from '../finance/finance.service';
import { ConsignmentMoneyDialogComponent, ConsignmentMoneyMode } from './consignment-money-dialog.component';
import { ConsignmentService } from './consignment.service';

/** One consignment agreement: terms, the car, and the money with its owner (rules 16, 17, P-06). */
@Component({
  selector: 'app-consignment-page',
  imports: [
    FormsModule,
    RouterLink,
    TranslocoPipe,
    ButtonModule,
    DialogModule,
    InputTextModule,
    TagModule,
    MoneyPipe,
    AppDatePipe,
    StateComponent,
    ConsignmentMoneyDialogComponent,
  ],
  template: `
    <a class="back" [routerLink]="['/t', context.activeTenantId(), 'consignments']">← {{ 'menu.consignments' | transloco }}</a>
    @if (loadError()) {
      <app-state kind="error" [message]="loadError()" (retry)="load()" />
    } @else if (consignment(); as c) {
      <div class="page-header">
        <div>
          <h1 class="page-title" data-testid="consignment-title">{{ c.vehicle_label }}</h1>
          <div class="meta">
            <a [routerLink]="['/t', context.activeTenantId(), 'vehicles', c.vehicle_id]" dir="ltr">{{ c.stock_no }}</a>
            <p-tag [value]="'consignment.status_' + c.status | transloco" data-testid="consignment-status"
                   [severity]="c.status === 'ACTIVE' ? 'info' : 'secondary'" />
            <span>{{ 'vehicles.status_' + c.vehicle_status | transloco }}</span>
          </div>
        </div>
        <div class="header-actions">
          <p-button icon="pi pi-file-pdf" [outlined]="true" [label]="'consignment.agreement' | transloco"
                    (onClick)="agreement()" data-testid="agreement-pdf" />
          @if (c.status === 'ACTIVE') {
            <p-button icon="pi pi-replay" severity="secondary" [label]="'consignment.returnToOwner' | transloco"
                      (onClick)="returnOpen.set(true)" data-testid="return-to-owner" />
          }
        </div>
      </div>

      <section class="card">
        <h2>{{ 'consignment.owner' | transloco }}</h2>
        <p><a [routerLink]="['/t', context.activeTenantId(), 'customers', c.consignor_id]">{{ c.consignor_name }}</a>
          <span dir="ltr"> {{ c.consignor_phone }}</span></p>
        <dl class="details">
          <div><dt>{{ 'consignment.terms' | transloco }}</dt><dd>{{ 'consignment.terms_' + c.terms_type | transloco }}:
            @if (c.terms_type === 'NET_PRICE') { {{ c.net_price_to_owner | money }} }
            @else if (c.terms_type === 'COMMISSION_PCT') { <span dir="ltr">{{ pct(c.commission_value) }}%</span> }
            @else { {{ c.commission_value | money }} }</dd></div>
          <div><dt>{{ 'consignment.expensesBorneBy' | transloco }}</dt>
            <dd>{{ 'consignment.borne_' + c.expenses_borne_by | transloco }}
              @if (c.shared_owner_pct) { ({{ pct(c.shared_owner_pct) }}%) }</dd></div>
          <div><dt>{{ 'consignment.agreementDate' | transloco }}</dt><dd>{{ c.agreement_date | appDate }}</dd></div>
          <div><dt>{{ 'consignment.endDate' | transloco }}</dt>
            <dd>{{ c.end_date ? (c.end_date | appDate) : '—' }}
              @if (c.expired) { <p-tag severity="warn" [value]="'consignment.expired' | transloco" /> }</dd></div>
          <div><dt>{{ 'vehicles.askingPrice' | transloco }}</dt><dd>{{ c.asking_price ? (c.asking_price | money) : '—' }}</dd></div>
          <div><dt>{{ 'consignment.daysWithUs' | transloco }}</dt><dd>{{ c.days_with_us }}</dd></div>
          @if (c.sale_id) {
            <div><dt>{{ 'vehicles.sale' | transloco }}</dt>
              <dd><a [routerLink]="['/t', context.activeTenantId(), 'sales', c.sale_id]">{{ c.sale_no }}</a> —
                {{ c.sale_price | money }}</dd></div>
          }
          @if (c.returned_date) {
            <div><dt>{{ 'consignment.returnedOn' | transloco }}</dt><dd>{{ c.returned_date | appDate }}</dd></div>
          }
        </dl>
        @if (c.notes) { <p class="sub">{{ c.notes }}</p> }
      </section>

      @if (c.payable !== undefined && c.payable !== null) {
        <section class="card" data-testid="owner-money">
          <h2>{{ 'consignment.ownerMoney' | transloco }}</h2>
          <div class="figures">
            @if (c.commission && c.commission !== '0.00') {
              <div class="figure"><span>{{ 'consignment.commission' | transloco }}</span><strong>{{ c.commission | money }}</strong></div>
            }
            <div class="figure"><span>{{ 'consignment.dueToOwner' | transloco }}</span>
              <strong data-testid="due-to-owner">{{ c.payable | money }}</strong></div>
            <div class="figure negative"><span>{{ 'consignment.ownerOwes' | transloco }}</span>
              <strong data-testid="owner-owes">{{ c.recoverable | money }}</strong></div>
          </div>
          <div class="actions">
            @if (c.payable !== '0.00') {
              <p-button icon="pi pi-send" [label]="'consignment.payOwner' | transloco" (onClick)="money('PAYOUT')"
                        [disabled]="accounts().length === 0" data-testid="pay-owner" />
            }
            @if (c.recoverable !== '0.00') {
              <p-button icon="pi pi-download" severity="secondary" [label]="'consignment.recover' | transloco"
                        (onClick)="money('RECOVERY')" [disabled]="accounts().length === 0" data-testid="recover" />
            }
            <a [routerLink]="['/t', context.activeTenantId(), 'customers', c.consignor_id]" class="link">
              {{ 'consignment.ownerStatement' | transloco }}</a>
          </div>
          @if (c.settlements?.length) {
            <ul class="list">
              @for (s of c.settlements; track s.id) {
                <li [class.muted]="s.status !== 'POSTED'">{{ s.settle_date | appDate }} —
                  {{ 'consignment.kind_' + s.kind | transloco }} <strong>{{ s.amount | money }}</strong>
                  ({{ s.cash_account_name_ar }}) <span class="sub">#{{ s.entry_no }}</span></li>
              }
            </ul>
          }
        </section>
        <app-consignment-money-dialog [(visible)]="moneyOpen" [mode]="moneyMode()" [targetId]="c.id"
                                      [outstanding]="moneyMode() === 'PAYOUT' ? c.payable : (c.recoverable ?? '0.00')"
                                      [accounts]="accounts()" (posted)="posted()" />
      }

      <p-dialog [(visible)]="returnOpen" [modal]="true" [header]="'consignment.returnToOwner' | transloco"
                [style]="{ width: 'min(420px, 96vw)' }">
        <div class="dialog-fields">
          <p class="sub">{{ 'consignment.returnHint' | transloco }}</p>
          <div class="field"><label for="ret-date">{{ 'finance.date' | transloco }}</label>
            <input pInputText id="ret-date" type="date" [(ngModel)]="returnDate" /></div>
          <div class="field"><label for="ret-reason">{{ 'vehicles.reason' | transloco }}</label>
            <input pInputText id="ret-reason" [(ngModel)]="returnReason" data-testid="return-reason" /></div>
          <p-button [label]="'consignment.returnToOwner' | transloco" (onClick)="returnToOwner()"
                    [disabled]="returnReason.trim().length < 3" data-testid="return-confirm" />
        </div>
      </p-dialog>
    } @else {
      <app-state kind="loading" />
    }
  `,
  styles: `
    .details {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: var(--space-2) var(--space-4);
      margin: 0;

      dt {
        font-size: 0.8rem;
        color: var(--color-text-muted);
      }
      dd {
        margin: 0;
      }
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      align-items: center;
      margin-block: var(--space-3);
    }
    .list {
      padding: 0;
      margin: 0;
      list-style: none;

      li {
        padding-block: var(--space-1);
        border-block-end: 1px solid var(--color-border);
      }
    }
  `,
})
export class ConsignmentPage implements OnInit {
  private readonly api = inject(ConsignmentService);
  private readonly finance = inject(FinanceService);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  private readonly language = inject(LanguageService);
  private readonly format = inject(FormatService);
  protected readonly context = inject(TenantContextService);

  readonly consignmentId = input.required<string>();

  protected readonly consignment = signal<Consignment | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly accounts = signal<CashAccount[]>([]);
  protected readonly moneyOpen = signal(false);
  protected readonly moneyMode = signal<ConsignmentMoneyMode>('PAYOUT');
  protected readonly returnOpen = signal(false);
  protected returnDate = '';
  protected returnReason = '';

  ngOnInit(): void {
    this.returnDate = this.format.todayIso();
    void this.load();
    if (this.context.can('cash.view')) {
      void this.finance.cashAccounts().then((a) => this.accounts.set(a));
    }
  }

  protected async load(): Promise<void> {
    try {
      this.consignment.set(await this.api.get(this.consignmentId()));
      this.loadError.set(null);
    } catch (error) {
      this.loadError.set(this.errors.message(error));
    }
  }

  protected pct(value: string | number | null | undefined): string {
    return value === null || value === undefined ? '' : String(Number(value));
  }

  protected money(mode: ConsignmentMoneyMode): void {
    this.moneyMode.set(mode);
    this.moneyOpen.set(true);
  }

  protected async posted(): Promise<void> {
    this.toast.add({ severity: 'success', summary: this.transloco.translate('finance.postedShort') });
    await this.load();
  }

  protected async returnToOwner(): Promise<void> {
    try {
      this.consignment.set(
        await this.api.returnToOwner(this.consignmentId(), { return_date: this.returnDate, reason: this.returnReason.trim() }),
      );
      this.returnOpen.set(false);
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    }
  }

  protected async agreement(): Promise<void> {
    try {
      const c = this.consignment();
      saveBlob(await this.api.agreementPdf(this.consignmentId(), this.language.language()), `consignment-${c?.stock_no}.pdf`);
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    }
  }
}
