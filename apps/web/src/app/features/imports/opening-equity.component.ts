import { Component, inject, OnInit, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { MessageModule } from 'primeng/message';

import { OpeningEquity } from '../../core/api/api.models';
import { FormatService, MoneyPipe } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { ErrorMessageService } from '../../shared/error-message.service';
import { moneySum, splitByWeights } from '../../shared/money-math';
import { ImportsService } from './imports.service';

interface Row {
  partner_id: string;
  name: string;
  account: 'CAPITAL' | 'CURRENT';
  amount: string;
}

/**
 * What the opening balances leave on opening balance equity (3900, Q-16) goes to
 * the partners by their agreement (P-08): suggested by ownership %, editable.
 */
@Component({
  selector: 'app-opening-equity',
  imports: [FormsModule, TranslocoPipe, ButtonModule, MessageModule, MoneyPipe],
  template: `
    @if (equity(); as e) {
      @if (e.balance !== '0.00') {
        <section class="card" data-testid="opening-equity">
          <h2>{{ 'imports.equityTitle' | transloco }}</h2>
          <p>{{ 'imports.equityHint' | transloco }} <strong data-testid="equity-balance">{{ e.balance | money }}</strong></p>
          <table class="rows">
            @for (row of rows; track row.partner_id) {
              <tr>
                <td>{{ row.name }}</td>
                <td>
                  <select [(ngModel)]="row.account" [attr.aria-label]="'imports.equityAccount' | transloco">
                    <option value="CAPITAL">{{ 'partners.capital' | transloco }}</option>
                    <option value="CURRENT">{{ 'partners.current' | transloco }}</option>
                  </select>
                </td>
                <td><input class="amount" [(ngModel)]="row.amount" inputmode="decimal" dir="ltr"
                           [attr.aria-label]="row.name" /></td>
              </tr>
            }
          </table>
          @if (error()) { <p-message severity="error">{{ error() }}</p-message> }
          <p-button [label]="'imports.equityConfirm' | transloco" (onClick)="confirm()" [loading]="busy()"
                    data-testid="equity-confirm" />
        </section>
      }
    }
  `,
  styles: `
    .rows td {
      padding: var(--space-1) var(--space-2);
    }
    .amount {
      inline-size: 140px;
      padding: 4px 8px;
      font: inherit;
    }
  `,
})
export class OpeningEquityComponent implements OnInit {
  private readonly api = inject(ImportsService);
  private readonly errors = inject(ErrorMessageService);
  private readonly format = inject(FormatService);
  private readonly language = inject(LanguageService);

  readonly cleared = output<void>();

  protected readonly equity = signal<OpeningEquity | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected rows: Row[] = [];
  private readonly key = crypto.randomUUID();

  async ngOnInit(): Promise<void> {
    await this.load();
  }

  async load(): Promise<void> {
    try {
      const equity = await this.api.openingEquity();
      this.equity.set(equity);
      const people = equity.partners as { partner_id: string; name_ar: string; name_en: string | null; percentage: string }[];
      const amounts = equity.balance.startsWith('-')
        ? people.map(() => '0.00')
        : splitByWeights(equity.balance, people.map((p) => p.percentage));
      this.rows = people.map((p, i) => ({
        partner_id: p.partner_id,
        name: this.language.language() === 'en' && p.name_en ? p.name_en : p.name_ar,
        account: 'CAPITAL',
        amount: amounts[i] ?? '0.00',
      }));
    } catch {
      this.equity.set(null);
    }
  }

  protected async confirm(): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      const lines = this.rows
        .filter((r) => r.amount && moneySum(r.amount) !== '0.00')
        .map((r) => ({ partner_id: r.partner_id, account: r.account, amount: moneySum(r.amount) }));
      await this.api.clearOpeningEquity({ clearing_date: this.format.todayIso(), lines }, this.key);
      await this.load();
      this.cleared.emit();
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }
}
