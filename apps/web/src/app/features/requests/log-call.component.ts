import { Component, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';

import { FollowUp, FollowUpResult } from '../../core/api/api.models';
import { FormatService } from '../../core/format/format.service';
import { ErrorMessageService } from '../../shared/error-message.service';
import { CrmService } from './crm.service';

const RESULTS: FollowUpResult[] = ['ANSWERED', 'NO_ANSWER', 'INTERESTED', 'CALL_BACK', 'NOT_INTERESTED'];
/** Results that ask for another call; the next follow-up defaults to tomorrow (D-98). */
const CALL_AGAIN: FollowUpResult[] = ['NO_ANSWER', 'CALL_BACK', 'INTERESTED'];

/**
 * Log a call in at most three taps (BACKLOG 6.4): open, pick the result — that
 * saves it. A note and the next date are optional before the result is picked.
 */
@Component({
  selector: 'app-log-call',
  imports: [FormsModule, TranslocoPipe, ButtonModule, InputTextModule],
  template: `
    @if (!open()) {
      <p-button icon="pi pi-phone" [label]="compact() ? '' : ('followUps.logCall' | transloco)" [outlined]="true" size="small"
                [ariaLabel]="'followUps.logCall' | transloco" (onClick)="start()" [attr.data-testid]="'log-call-' + testKey()" />
    } @else {
      <div class="panel" [attr.data-testid]="'log-call-panel-' + testKey()">
        @if (phone()) {
          <a class="dial" [href]="'tel:' + phone()" dir="ltr"><i class="pi pi-phone" aria-hidden="true"></i> {{ phone() }}</a>
        }
        <input pInputText [(ngModel)]="note" [placeholder]="'followUps.note' | transloco"
               [attr.aria-label]="'followUps.note' | transloco" />
        <label class="next">{{ 'followUps.next' | transloco }}
          <input pInputText type="date" [(ngModel)]="nextDate" />
        </label>
        <div class="results">
          @for (result of results; track result) {
            <p-button size="small" [label]="'followUps.result_' + result | transloco" [loading]="busy() === result"
                      [disabled]="busy() !== null" [severity]="result === 'NOT_INTERESTED' ? 'secondary' : 'primary'"
                      [outlined]="result !== 'ANSWERED'" (onClick)="save(result)" [attr.data-testid]="'call-' + result" />
          }
          <p-button size="small" [text]="true" icon="pi pi-times" [ariaLabel]="'common.cancel' | transloco"
                    (onClick)="open.set(false)" />
        </div>
        @if (error()) { <p class="negative">{{ error() }}</p> }
      </div>
    }
  `,
  styles: `
    .panel {
      display: grid;
      gap: var(--space-2);
      padding: var(--space-2);
      border: 1px solid var(--color-border);
      border-radius: var(--radius-md, 8px);
    }
    .results {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-1);
    }
    .next {
      display: flex;
      gap: var(--space-2);
      align-items: center;
      font-size: 0.875rem;
    }
    .dial {
      font-weight: 600;
    }
  `,
})
export class LogCallComponent {
  private readonly api = inject(CrmService);
  private readonly format = inject(FormatService);
  private readonly errors = inject(ErrorMessageService);

  readonly customerId = input.required<string>();
  readonly requestId = input<string | null>(null);
  readonly phone = input<string | null>(null);
  readonly compact = input(false);
  readonly testKey = input('');
  readonly logged = output<FollowUp>();

  protected readonly open = signal(false);
  protected readonly busy = signal<FollowUpResult | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly results = RESULTS;
  protected note = '';
  protected nextDate = '';

  protected start(): void {
    this.note = '';
    this.nextDate = '';
    this.error.set(null);
    this.open.set(true);
  }

  protected async save(result: FollowUpResult): Promise<void> {
    this.busy.set(result);
    this.error.set(null);
    try {
      const next = this.nextDate || (CALL_AGAIN.includes(result) ? this.tomorrow() : null);
      const followUp = await this.api.logFollowUp({
        customer_id: this.customerId(),
        request_id: this.requestId(),
        kind: 'CALL',
        result,
        notes: this.note.trim() || null,
        next_follow_up_date: next,
        priority: 'NORMAL',
      });
      this.open.set(false);
      this.logged.emit(followUp);
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(null);
    }
  }

  private tomorrow(): string {
    const today = new Date(`${this.format.todayIso()}T12:00:00Z`);
    today.setUTCDate(today.getUTCDate() + 1);
    return today.toISOString().slice(0, 10);
  }
}
