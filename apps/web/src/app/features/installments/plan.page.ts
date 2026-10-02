import { Component, inject, input, OnInit, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';

import { CashAccount, InstallmentPlan, Paper } from '../../core/api/api.models';
import { AppDatePipe, MoneyPipe } from '../../core/format/format.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { FinanceService } from '../finance/finance.service';
import { InstallmentsService } from './installments.service';
import { nextActions, PaperActionDialogComponent } from './paper-action-dialog.component';
import { PaperFormDialogComponent } from './paper-form-dialog.component';
import { ReceiptDialogComponent } from './receipt-dialog.component';

/** One installment plan: schedule with derived states, receipts, and its papers. */
@Component({
  selector: 'app-plan-page',
  imports: [
    RouterLink,
    TranslocoPipe,
    ButtonModule,
    TableModule,
    TagModule,
    MoneyPipe,
    AppDatePipe,
    CanDirective,
    StateComponent,
    ReceiptDialogComponent,
    PaperFormDialogComponent,
    PaperActionDialogComponent,
  ],
  template: `
    <a class="back" [routerLink]="['/t', context.activeTenantId(), 'installments']">← {{ 'installments.title' | transloco }}</a>
    @if (loadError()) {
      <app-state kind="error" [message]="loadError()" (retry)="load()" />
    } @else if (plan(); as p) {
      <div class="page-header">
        <div>
          <h1 class="page-title" data-testid="plan-title">{{ p.customer_name }} — {{ p.vehicle_label }}</h1>
          <div class="meta">
            <a [routerLink]="['/t', context.activeTenantId(), 'sales', p.sale_id]">{{ p.sale_no }}</a>
            <a [routerLink]="['/t', context.activeTenantId(), 'customers', p.customer_id]">{{ 'installments.customerStatement' | transloco }}</a>
            @if (p.status === 'CANCELLED') { <p-tag severity="danger" [value]="'sales.status_CANCELLED' | transloco" /> }
          </div>
        </div>
        @if (p.status === 'ACTIVE' && p.remaining_total !== '0.00') {
          <div class="header-actions">
            <p-button *appCan="'installment.collect'" icon="pi pi-money-bill" data-testid="collect"
                      [label]="'installments.collect' | transloco" (onClick)="collectOpen.set(true)"
                      [disabled]="accounts().length === 0" />
            <p-button *appCan="'deferred_paper.manage'" icon="pi pi-file-plus" severity="secondary" data-testid="add-paper"
                      [label]="'papers.add' | transloco" (onClick)="paperOpen.set(true)" />
          </div>
        }
      </div>

      <div class="figures card">
        <div class="figure"><span>{{ 'installments.financed' | transloco }}</span><strong>{{ p.financed_amount | money }}</strong></div>
        <div class="figure"><span>{{ 'installments.paid' | transloco }}</span><strong>{{ p.paid_total | money }}</strong></div>
        <div class="figure"><span>{{ 'installments.remaining' | transloco }}</span>
          <strong data-testid="plan-remaining">{{ p.remaining_total | money }}</strong></div>
        <div class="figure negative"><span>{{ 'installments.overdue' | transloco }}</span><strong>{{ p.overdue_total | money }}</strong></div>
      </div>

      <p-table [value]="p.installments" styleClass="p-datatable-sm" data-testid="schedule">
        <ng-template #header>
          <tr>
            <th>#</th>
            <th>{{ 'papers.dueDate' | transloco }}</th>
            <th class="num">{{ 'finance.amount' | transloco }}</th>
            <th class="num">{{ 'installments.paid' | transloco }}</th>
            <th class="num">{{ 'installments.remaining' | transloco }}</th>
            <th>{{ 'vehicles.status' | transloco }}</th>
          </tr>
        </ng-template>
        <ng-template #body let-i>
          <tr [attr.data-testid]="'seq-' + i.seq">
            <td>{{ i.seq }}</td>
            <td>{{ i.due_date | appDate }}</td>
            <td class="num">{{ i.amount_due | money }}</td>
            <td class="num">{{ i.paid | money }}</td>
            <td class="num strong">{{ i.remaining | money }}</td>
            <td>
              <p-tag [severity]="severity(i.state)" [value]="'installments.state_' + i.state | transloco" />
              @if (i.days_late > 0) { <span class="sub negative"> {{ 'installments.daysLate' | transloco: { n: i.days_late } }}</span> }
            </td>
          </tr>
        </ng-template>
      </p-table>

      @if (p.receipts.length) {
        <section class="card">
          <h2>{{ 'installments.receipts' | transloco }}</h2>
          <ul class="list" data-testid="receipts">
            @for (r of p.receipts; track r.id) {
              <li [class.muted]="r.status !== 'POSTED'">
                {{ r.receipt_date | appDate }} — <strong>{{ r.amount | money }}</strong>
                ({{ r.cash_account_name_ar ?? ('installments.fromCredit' | transloco) }})
                <span class="sub">#{{ r.entry_no }} · @for (a of r.allocations; track a.seq) { {{ 'installments.installment' | transloco }} {{ a.seq }} }</span>
                @if (r.status === 'BOUNCED') { <p-tag severity="danger" [value]="'installments.bounced' | transloco" /> }
              </li>
            }
          </ul>
        </section>
      }

      @if (p.papers.length) {
        <section class="card">
          <h2>{{ 'papers.title' | transloco }}</h2>
          <ul class="list" data-testid="plan-papers">
            @for (paper of p.papers; track paper.id) {
              <li>
                {{ 'papers.type_' + paper.paper_type | transloco }} <span dir="ltr">{{ paper.number }}</span> —
                {{ paper.amount | money }} — {{ paper.due_date | appDate }}
                <p-tag [severity]="paper.overdue ? 'danger' : 'secondary'" [value]="'papers.status_' + paper.status | transloco" />
                @if (actionsFor(paper).length) {
                  <p-button *appCan="'deferred_paper.manage'" [text]="true" size="small" [label]="'papers.actionTitle' | transloco"
                            (onClick)="act(paper)" [attr.data-testid]="'paper-act-' + paper.number" />
                }
              </li>
            }
          </ul>
        </section>
      }

      <app-receipt-dialog [(visible)]="collectOpen" [planId]="p.id" [owed]="p.remaining_total"
                          [suggested]="nextDue()" [accounts]="accounts()" (posted)="done()" />
      <app-paper-form-dialog [(visible)]="paperOpen" [plan]="p" (saved)="load()" />
      @if (acting(); as paper) {
        <app-paper-action-dialog [(visible)]="actionOpen" [paper]="paper" [accounts]="accounts()" (posted)="done()" />
      }
    } @else {
      <app-state kind="loading" />
    }
  `,
  styles: `
    .list {
      padding: 0;
      margin: 0;
      list-style: none;

      li {
        display: flex;
        flex-wrap: wrap;
        gap: var(--space-1) var(--space-2);
        align-items: center;
        padding-block: var(--space-1);
        border-block-end: 1px solid var(--color-border);
      }
    }
  `,
})
export class PlanPage implements OnInit {
  private readonly api = inject(InstallmentsService);
  private readonly finance = inject(FinanceService);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  protected readonly context = inject(TenantContextService);

  readonly planId = input.required<string>();

  protected readonly plan = signal<InstallmentPlan | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly accounts = signal<CashAccount[]>([]);
  protected readonly collectOpen = signal(false);
  protected readonly paperOpen = signal(false);
  protected readonly actionOpen = signal(false);
  protected readonly acting = signal<Paper | null>(null);
  protected readonly actionsFor = nextActions;

  ngOnInit(): void {
    void this.load();
    if (this.context.can('cash.view')) {
      void this.finance.cashAccounts().then((a) => this.accounts.set(a));
    }
  }

  protected async load(): Promise<void> {
    try {
      this.plan.set(await this.api.plan(this.planId()));
      this.loadError.set(null);
    } catch (error) {
      this.loadError.set(this.errors.message(error));
    }
  }

  protected nextDue(): string {
    return this.plan()?.installments.find((i) => i.remaining !== '0.00' && i.state !== 'CANCELLED')?.remaining ?? '';
  }

  protected act(paper: Paper): void {
    this.acting.set(paper);
    this.actionOpen.set(true);
  }

  protected async done(): Promise<void> {
    this.toast.add({ severity: 'success', summary: this.transloco.translate('finance.postedShort') });
    await this.load();
  }

  protected severity(state: string): 'success' | 'danger' | 'warn' | 'info' | 'secondary' {
    return state === 'PAID' ? 'success' : state === 'OVERDUE' ? 'danger' : state === 'DUE_TODAY' ? 'warn' : state === 'UPCOMING' ? 'info' : 'secondary';
  }
}
