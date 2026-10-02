import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';

import { CashAccount, Installment, InstallmentBoard } from '../../core/api/api.models';
import { AppDatePipe, FormatService, MoneyPipe } from '../../core/format/format.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { loaded, translationsLoaded } from '../../shared/translated';
import { FinanceService } from '../finance/finance.service';
import { BoardView, InstallmentsService } from './installments.service';
import { ReceiptDialogComponent } from './receipt-dialog.component';

type View = BoardView | 'calendar';

interface Day {
  iso: string;
  day: number;
  inMonth: boolean;
  items: Installment[];
}

/** Monday-first weeks covering a month, as ISO dates (pure, unit-tested). */
export function monthGrid(year: number, month: number): { iso: string; day: number; inMonth: boolean }[] {
  const first = new Date(Date.UTC(year, month - 1, 1));
  const start = new Date(first);
  start.setUTCDate(1 - ((first.getUTCDay() + 6) % 7));
  const cells = [];
  for (let i = 0; i < 42; i++) {
    const day = new Date(start);
    day.setUTCDate(start.getUTCDate() + i);
    cells.push({ iso: day.toISOString().slice(0, 10), day: day.getUTCDate(), inMonth: day.getUTCMonth() === month - 1 });
  }
  return cells.slice(0, cells[35].inMonth ? 42 : 35);
}

/**
 * Installments board (SPEC §4.8): due today, next 7 days, overdue with days
 * late, totals per customer, and a calendar "radar" coloured by state.
 */
@Component({
  selector: 'app-installments-page',
  imports: [
    FormsModule,
    RouterLink,
    TranslocoPipe,
    ButtonModule,
    SelectButtonModule,
    TableModule,
    TagModule,
    MoneyPipe,
    AppDatePipe,
    CanDirective,
    StateComponent,
    ReceiptDialogComponent,
  ],
  templateUrl: './installments.page.html',
  styleUrl: './installments.page.scss',
})
export class InstallmentsPage implements OnInit {
  private readonly api = inject(InstallmentsService);
  private readonly finance = inject(FinanceService);
  private readonly router = inject(Router);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  private readonly format = inject(FormatService);
  private readonly translations = translationsLoaded();
  protected readonly context = inject(TenantContextService);

  protected readonly board = signal<InstallmentBoard | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly loading = signal(false);
  protected readonly accounts = signal<CashAccount[]>([]);
  protected view: View = 'overdue';
  protected readonly calendarItems = signal<Installment[]>([]);
  protected readonly month = signal(this.format.todayIso().slice(0, 7));
  protected readonly collecting = signal<Installment | null>(null);
  protected readonly collectOpen = signal(false);

  protected readonly viewOptions = computed(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    return (['overdue', 'due_today', 'upcoming', 'open', 'calendar'] as const).map((value) => ({
      value,
      label: this.transloco.translate(`installments.view_${value}`),
    }));
  });
  protected readonly days = computed<Day[]>(() => {
    const [year, month] = this.month().split('-').map(Number);
    const byDate = new Map<string, Installment[]>();
    for (const item of this.calendarItems()) {
      byDate.set(item.due_date, [...(byDate.get(item.due_date) ?? []), item]);
    }
    return monthGrid(year, month).map((cell) => ({ ...cell, items: byDate.get(cell.iso) ?? [] }));
  });
  protected readonly weekdays = computed(() => {
    const locale = this.transloco.getActiveLang() === 'ar' ? 'ar-EG' : 'en-GB';
    // 2024-01-01 was a Monday.
    return [...Array(7).keys()].map((i) =>
      new Intl.DateTimeFormat(locale, { weekday: 'short', timeZone: 'UTC' }).format(new Date(Date.UTC(2024, 0, 1 + i))),
    );
  });

  ngOnInit(): void {
    void this.load();
    if (this.context.can('cash.view')) {
      void this.finance.cashAccounts().then((a) => this.accounts.set(a));
    }
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    try {
      if (this.view === 'calendar') {
        const [year, month] = this.month().split('-').map(Number);
        const cells = monthGrid(year, month);
        this.calendarItems.set(await this.api.calendar(cells[0].iso, cells[cells.length - 1].iso));
      } else {
        this.board.set(await this.api.board(this.view, 7));
      }
      this.loadError.set(null);
    } catch (error) {
      this.loadError.set(this.errors.message(error));
    } finally {
      this.loading.set(false);
    }
  }

  protected shiftMonth(delta: number): void {
    const [year, month] = this.month().split('-').map(Number);
    const next = new Date(Date.UTC(year, month - 1 + delta, 1));
    this.month.set(next.toISOString().slice(0, 7));
    void this.load();
  }

  protected monthLabel(): string {
    const [year, month] = this.month().split('-').map(Number);
    const locale = this.transloco.getActiveLang() === 'ar' ? 'ar-EG-u-nu-latn' : 'en-GB';
    return new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(
      new Date(Date.UTC(year, month - 1, 1)),
    );
  }

  protected open(row: Installment): void {
    void this.router.navigate(['/t', this.context.activeTenantId(), 'installments', 'plans', row.plan_id]);
  }

  protected collect(row: Installment, event: Event): void {
    event.stopPropagation();
    this.collecting.set(row);
    this.collectOpen.set(true);
  }

  protected async collected(): Promise<void> {
    this.toast.add({ severity: 'success', summary: this.transloco.translate('finance.postedShort') });
    await this.load();
  }

  protected severity(state: Installment['state']): 'success' | 'danger' | 'warn' | 'info' | 'secondary' {
    switch (state) {
      case 'PAID':
        return 'success';
      case 'OVERDUE':
        return 'danger';
      case 'DUE_TODAY':
        return 'warn';
      case 'UPCOMING':
        return 'info';
      default:
        return 'secondary';
    }
  }
}
