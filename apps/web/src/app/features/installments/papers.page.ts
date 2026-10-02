import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';

import { CashAccount, Paper } from '../../core/api/api.models';
import { AppDatePipe, MoneyPipe } from '../../core/format/format.service';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { loaded, translationsLoaded } from '../../shared/translated';
import { FinanceService } from '../finance/finance.service';
import { InstallmentsService } from './installments.service';
import { nextActions, PaperActionDialogComponent } from './paper-action-dialog.component';

const STATUSES = ['HELD', 'DEPOSITED', 'COLLECTED', 'BOUNCED', 'RETURNED', 'DEFAULTED', 'LEGAL'] as const;

/** Deferred papers register (سجل الأوراق الآجلة, SPEC §4.8): notes and post-dated cheques. */
@Component({
  selector: 'app-papers-page',
  imports: [
    FormsModule,
    RouterLink,
    TranslocoPipe,
    ButtonModule,
    CheckboxModule,
    DialogModule,
    SelectModule,
    TableModule,
    TagModule,
    MoneyPipe,
    AppDatePipe,
    StateComponent,
    PaperActionDialogComponent,
  ],
  template: `
    <a class="back" [routerLink]="['/t', context.activeTenantId(), 'installments']">← {{ 'installments.title' | transloco }}</a>
    <div class="page-header"><h1 class="page-title">{{ 'papers.title' | transloco }}</h1></div>
    <div class="filters">
      <p-select [options]="statusOptions()" [(ngModel)]="status" (ngModelChange)="load()" optionLabel="label"
                optionValue="value" [showClear]="true" [placeholder]="'papers.allStatuses' | transloco" />
      <p-select [options]="typeOptions()" [(ngModel)]="type" (ngModelChange)="load()" optionLabel="label"
                optionValue="value" [showClear]="true" [placeholder]="'papers.allTypes' | transloco" />
      <div class="check">
        <p-checkbox [(ngModel)]="overdue" (ngModelChange)="load()" [binary]="true" inputId="p-overdue" />
        <label for="p-overdue">{{ 'papers.overdueOnly' | transloco }}</label>
      </div>
    </div>
    @if (loadError()) {
      <app-state kind="error" [message]="loadError()" (retry)="load()" />
    } @else {
      <p-table [value]="papers()" styleClass="p-datatable-sm" data-testid="papers">
        <ng-template #header>
          <tr>
            <th>{{ 'papers.number' | transloco }}</th>
            <th>{{ 'sales.customer' | transloco }}</th>
            <th class="num">{{ 'finance.amount' | transloco }}</th>
            <th>{{ 'papers.dueDate' | transloco }}</th>
            <th>{{ 'vehicles.status' | transloco }}</th>
            <th>{{ 'papers.storageLocation' | transloco }}</th>
            <th></th>
          </tr>
        </ng-template>
        <ng-template #body let-p>
          <tr [attr.data-testid]="'paper-' + p.number">
            <td>{{ 'papers.type_' + p.paper_type | transloco }}<div dir="ltr">{{ p.number }}</div>
              @if (p.drawer_bank) { <div class="sub">{{ p.drawer_bank }} {{ p.drawer_branch }}</div> }</td>
            <td>{{ p.customer_name }}@if (p.sale_no) { <div class="sub">{{ p.sale_no }} #{{ p.installment_seq }}</div> }</td>
            <td class="num">{{ p.amount | money }}</td>
            <td>{{ p.due_date | appDate }}@if (p.overdue) { <p-tag severity="danger" [value]="'installments.state_OVERDUE' | transloco" /> }</td>
            <td><p-tag [severity]="p.status === 'BOUNCED' ? 'danger' : p.status === 'COLLECTED' || p.status === 'RETURNED' ? 'success' : 'secondary'"
                       [value]="'papers.status_' + p.status | transloco" /></td>
            <td class="sub">{{ p.storage_location }}</td>
            <td class="actions-cell">
              <p-button [text]="true" size="small" icon="pi pi-history" [ariaLabel]="'vehicles.history' | transloco"
                        (onClick)="showHistory(p)" />
              @if (actionsFor(p).length) {
                <p-button [text]="true" size="small" [label]="'papers.actionTitle' | transloco" (onClick)="act(p)"
                          [attr.data-testid]="'paper-act-' + p.number" />
              }
            </td>
          </tr>
        </ng-template>
        <ng-template #emptymessage>
          <tr><td colspan="7"><app-state kind="empty" [message]="'papers.none' | transloco" /></td></tr>
        </ng-template>
      </p-table>
    }

    @if (acting(); as paper) {
      <app-paper-action-dialog [(visible)]="actionOpen" [paper]="paper" [accounts]="accounts()" (posted)="done()" />
    }
    <p-dialog [(visible)]="historyOpen" [modal]="true" [header]="'vehicles.history' | transloco" [style]="{ width: 'min(480px, 96vw)' }">
      @if (history(); as h) {
        <ul class="events">
          @for (e of h.events; track $index) {
            <li><span class="sub">{{ e.event_date | appDate }}</span> {{ 'papers.status_' + e.to_status | transloco }}
              @if (e.entry_no) { <span class="sub">#{{ e.entry_no }}</span> } @if (e.note) { — {{ e.note }} }</li>
          }
        </ul>
      }
    </p-dialog>
  `,
  styles: `
    .check {
      display: flex;
      gap: var(--space-2);
      align-items: center;
    }
    .actions-cell {
      white-space: nowrap;
    }
    .events {
      padding: 0;
      list-style: none;

      li {
        padding-block: var(--space-1);
        border-block-end: 1px solid var(--color-border);
      }
    }
  `,
})
export class PapersPage implements OnInit {
  private readonly api = inject(InstallmentsService);
  private readonly finance = inject(FinanceService);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  private readonly translations = translationsLoaded();
  protected readonly context = inject(TenantContextService);

  protected readonly papers = signal<Paper[]>([]);
  protected readonly loadError = signal<string | null>(null);
  protected readonly accounts = signal<CashAccount[]>([]);
  protected readonly acting = signal<Paper | null>(null);
  protected readonly actionOpen = signal(false);
  protected readonly history = signal<Paper | null>(null);
  protected readonly historyOpen = signal(false);
  protected readonly actionsFor = nextActions;
  protected status: string | null = null;
  protected type: string | null = null;
  protected overdue = false;

  protected readonly statusOptions = computed(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    return STATUSES.map((value) => ({ value, label: this.transloco.translate(`papers.status_${value}`) }));
  });
  protected readonly typeOptions = computed(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    return (['PDC', 'PROMISSORY_NOTE'] as const).map((value) => ({ value, label: this.transloco.translate(`papers.type_${value}`) }));
  });

  ngOnInit(): void {
    void this.load();
    if (this.context.can('cash.view')) {
      void this.finance.cashAccounts().then((a) => this.accounts.set(a));
    }
  }

  protected async load(): Promise<void> {
    try {
      this.papers.set(await this.api.papers({ status: this.status, paper_type: this.type, overdue: this.overdue }));
      this.loadError.set(null);
    } catch (error) {
      this.loadError.set(this.errors.message(error));
    }
  }

  protected act(paper: Paper): void {
    this.acting.set(paper);
    this.actionOpen.set(true);
  }

  protected async showHistory(paper: Paper): Promise<void> {
    this.history.set(await this.api.paper(paper.id));
    this.historyOpen.set(true);
  }

  protected async done(): Promise<void> {
    this.toast.add({ severity: 'success', summary: this.transloco.translate('finance.postedShort') });
    await this.load();
  }
}
