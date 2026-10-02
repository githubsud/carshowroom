import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';

import { Period } from '../../core/api/api.models';
import { AppDatePipe, FormatService } from '../../core/format/format.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { FinanceService } from './finance.service';

/** Month locking (SPEC §4.11): no posting or reversal dated inside a locked month. */
@Component({
  selector: 'app-periods-page',
  imports: [
    FormsModule,
    TranslocoPipe,
    ButtonModule,
    DialogModule,
    InputTextModule,
    MessageModule,
    TableModule,
    TagModule,
    TextareaModule,
    AppDatePipe,
    CanDirective,
    StateComponent,
  ],
  template: `
    <div class="page-header">
      <h1 class="page-title">{{ 'periods.title' | transloco }}</h1>
      <form class="lock-form" *appCan="'period.lock'" (ngSubmit)="lock(month)">
        <input pInputText type="month" [(ngModel)]="month" name="month" data-testid="lock-month" />
        <p-button type="submit" icon="pi pi-lock" data-testid="lock-submit" [label]="'periods.lock' | transloco"
                  [disabled]="!month" [loading]="busy() === month" />
      </form>
    </div>
    <p class="hint">{{ 'periods.hint' | transloco }}</p>

    @if (loadError()) {
      <app-state kind="error" [message]="loadError()" (retry)="load()" />
    } @else {
      <p-table [value]="periods()" [loading]="loading()" styleClass="p-datatable-sm" data-testid="periods-table">
        <ng-template #header>
          <tr>
            <th>{{ 'periods.month' | transloco }}</th>
            <th>{{ 'periods.status' | transloco }}</th>
            <th>{{ 'periods.entries' | transloco }}</th>
            <th>{{ 'periods.lockedAt' | transloco }}</th>
            <th></th>
          </tr>
        </ng-template>
        <ng-template #body let-p>
          <tr [attr.data-testid]="'period-' + p.month">
            <td>{{ p.month }}</td>
            <td>
              <p-tag [severity]="p.status === 'LOCKED' ? 'danger' : 'success'"
                     [value]="'periods.status_' + p.status | transloco" />
            </td>
            <td>{{ p.entry_count }}</td>
            <td>{{ p.locked_at | appDate }}</td>
            <td class="actions">
              @if (p.status === 'OPEN') {
                <p-button *appCan="'period.lock'" icon="pi pi-lock" [text]="true" [label]="'periods.lock' | transloco"
                          [loading]="busy() === p.month" (onClick)="lock(p.month)" />
              } @else {
                <p-button *appCan="'period.unlock'" icon="pi pi-lock-open" [text]="true" severity="danger"
                          [label]="'periods.unlock' | transloco" (onClick)="askUnlock(p)"
                          [attr.data-testid]="'unlock-' + p.month" />
              }
            </td>
          </tr>
        </ng-template>
        <ng-template #emptymessage>
          <tr><td colspan="5"><app-state kind="empty" /></td></tr>
        </ng-template>
      </p-table>
    }

    <p-dialog [visible]="!!unlocking()" (visibleChange)="!$event && unlocking.set(null)" [modal]="true"
              [header]="('periods.unlock' | transloco) + ' ' + (unlocking()?.month ?? '')" [style]="{ width: 'min(420px, 95vw)' }">
      <div class="unlock-form">
        <label for="unlock-reason">{{ 'journal.reasonLabel' | transloco }}</label>
        <textarea pTextarea id="unlock-reason" rows="2" [(ngModel)]="reason" data-testid="unlock-reason"></textarea>
        @if (error()) { <p-message severity="error">{{ error() }}</p-message> }
        <div class="dialog-actions">
          <p-button [text]="true" [label]="'common.cancel' | transloco" (onClick)="unlocking.set(null)" />
          <p-button severity="danger" data-testid="unlock-confirm" [label]="'periods.unlock' | transloco"
                    [disabled]="reason.trim().length < 3" [loading]="!!busy()" (onClick)="unlock()" />
        </div>
      </div>
    </p-dialog>
  `,
  styles: `
    .page-header {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      align-items: center;
      justify-content: space-between;
    }

    .lock-form {
      display: flex;
      gap: var(--space-2);
    }

    .hint {
      margin-block: 0 var(--space-3);
      color: var(--color-text-muted);
    }

    .actions {
      text-align: end;
    }

    .unlock-form {
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
    }

    .dialog-actions {
      display: flex;
      gap: var(--space-2);
      justify-content: flex-end;
    }
  `,
})
export class PeriodsPage implements OnInit {
  private readonly finance = inject(FinanceService);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);

  protected readonly periods = signal<Period[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly busy = signal<string | null>(null);
  protected readonly unlocking = signal<Period | null>(null);
  protected readonly error = signal<string | null>(null);
  protected month = inject(FormatService).todayIso().slice(0, 7);
  protected reason = '';

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.loadError.set(null);
    try {
      this.periods.set(await this.finance.periods());
    } catch (error) {
      this.loadError.set(this.errors.message(error));
    } finally {
      this.loading.set(false);
    }
  }

  protected async lock(month: string): Promise<void> {
    this.busy.set(month);
    try {
      await this.finance.lockPeriod(month);
      this.toast.add({ severity: 'success', summary: this.transloco.translate('periods.locked', { month }) });
      await this.load();
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    } finally {
      this.busy.set(null);
    }
  }

  protected askUnlock(period: Period): void {
    this.reason = '';
    this.error.set(null);
    this.unlocking.set(period);
  }

  protected async unlock(): Promise<void> {
    const period = this.unlocking();
    if (!period) {
      return;
    }
    this.busy.set(period.month);
    this.error.set(null);
    try {
      await this.finance.unlockPeriod(period.month, this.reason.trim());
      this.unlocking.set(null);
      await this.load();
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(null);
    }
  }
}
