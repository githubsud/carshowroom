import { Component, inject, input, OnInit, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';

import { CashAccount, ExternalShowroomStatement } from '../../core/api/api.models';
import { AppDatePipe, MoneyPipe } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { saveBlob } from '../../shared/download';
import { ErrorMessageService } from '../../shared/error-message.service';
import { FinanceService } from '../finance/finance.service';
import { ConsignmentMoneyDialogComponent } from './consignment-money-dialog.component';
import { ConsignmentService } from './consignment.service';

/** One external showroom: our cars there, what it owes us (1420) line by line, and collections (rule 19). */
@Component({
  selector: 'app-showroom-page',
  imports: [
    RouterLink,
    TranslocoPipe,
    ButtonModule,
    TableModule,
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
    } @else if (statement(); as s) {
      <div class="page-header">
        <div>
          <h1 class="page-title" data-testid="showroom-title">{{ s.name }}</h1>
          <div class="meta"><span dir="ltr">{{ s.phone }}</span></div>
        </div>
        <div class="header-actions">
          @if (s.receivable !== '0.00') {
            <p-button icon="pi pi-download" [label]="'consignment.collect' | transloco" (onClick)="collectOpen.set(true)"
                      [disabled]="accounts().length === 0" data-testid="collect" />
          }
          <p-button icon="pi pi-file-pdf" [outlined]="true" label="PDF" (onClick)="pdf()" />
        </div>
      </div>
      <div class="figures card">
        <div class="figure"><span>{{ 'consignment.dueToUs' | transloco }}</span>
          <strong data-testid="showroom-receivable">{{ s.receivable | money }}</strong></div>
        <div class="figure"><span>{{ 'consignment.carsOut' | transloco }}</span><strong>{{ carsOut() }}</strong></div>
      </div>

      <section class="card">
        <h2>{{ 'consignment.cars' | transloco }}</h2>
        <ul class="list" data-testid="showroom-cars">
          @for (car of s.cars; track car.id) {
            <li>
              <a [routerLink]="['/t', context.activeTenantId(), 'vehicles', car.vehicle_id]">{{ car.vehicle_label }}
                ({{ car.stock_no }})</a>
              <span class="sub">{{ car.sent_date | appDate }} · {{ 'consignment.daysN' | transloco: { n: car.days_out } }}</span>
              <p-tag [value]="'consignment.outStatus_' + car.status | transloco" [severity]="car.status === 'OUT' ? 'info' : 'secondary'" />
              @if (car.sale_price) { — {{ car.sale_price | money }} }
            </li>
          } @empty {
            <li class="sub">{{ 'consignment.noneOut' | transloco }}</li>
          }
        </ul>
      </section>

      <p-table [value]="s.lines" styleClass="p-datatable-sm" data-testid="showroom-statement">
        <ng-template #header>
          <tr>
            <th>{{ 'finance.date' | transloco }}</th>
            <th>{{ 'finance.description' | transloco }}</th>
            <th class="num">{{ 'consignment.debit' | transloco }}</th>
            <th class="num">{{ 'consignment.credit' | transloco }}</th>
            <th class="num">{{ 'consignment.balance' | transloco }}</th>
          </tr>
        </ng-template>
        <ng-template #body let-line>
          <tr>
            <td>{{ line.entry_date | appDate }}<div class="sub">#{{ line.entry_no }}</div></td>
            <td>{{ line.description }}</td>
            <td class="num">{{ line.debit !== '0.00' ? (line.debit | money) : '' }}</td>
            <td class="num">{{ line.credit !== '0.00' ? (line.credit | money) : '' }}</td>
            <td class="num strong">{{ line.balance | money }}</td>
          </tr>
        </ng-template>
      </p-table>
      <app-consignment-money-dialog [(visible)]="collectOpen" mode="COLLECTION" [targetId]="s.external_showroom_id"
                                    [outstanding]="s.receivable" [accounts]="accounts()" (posted)="posted()" />
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
        gap: var(--space-2);
        align-items: center;
        padding-block: var(--space-1);
        border-block-end: 1px solid var(--color-border);
      }
    }
  `,
})
export class ShowroomPage implements OnInit {
  private readonly api = inject(ConsignmentService);
  private readonly finance = inject(FinanceService);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  private readonly language = inject(LanguageService);
  protected readonly context = inject(TenantContextService);

  readonly showroomId = input.required<string>();

  protected readonly statement = signal<ExternalShowroomStatement | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly accounts = signal<CashAccount[]>([]);
  protected readonly collectOpen = signal(false);

  ngOnInit(): void {
    void this.load();
    if (this.context.can('cash.view')) {
      void this.finance.cashAccounts().then((a) => this.accounts.set(a));
    }
  }

  protected async load(): Promise<void> {
    try {
      this.statement.set(await this.api.showroomStatement(this.showroomId()));
      this.loadError.set(null);
    } catch (error) {
      this.loadError.set(this.errors.message(error));
    }
  }

  protected carsOut(): number {
    return this.statement()?.cars.filter((c) => c.status === 'OUT').length ?? 0;
  }

  protected async posted(): Promise<void> {
    this.toast.add({ severity: 'success', summary: this.transloco.translate('finance.postedShort') });
    await this.load();
  }

  protected async pdf(): Promise<void> {
    try {
      saveBlob(await this.api.showroomStatementPdf(this.showroomId(), this.language.language()), 'showroom-statement.pdf');
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    }
  }
}
