import { Component, inject, input } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { MessageModule } from 'primeng/message';

import { Preview } from '../../core/api/api.models';
import { MoneyPipe } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';

/**
 * Plain-language preview shown before every posting (SPEC §9.3): the sentence,
 * the money effects, warnings, and — only for users with journal access — the
 * debit/credit lines.
 */
@Component({
  selector: 'app-posting-preview',
  imports: [TranslocoPipe, MessageModule, MoneyPipe],
  template: `
    @let p = preview();
    <p class="summary" data-testid="preview-summary">{{ language.language() === 'ar' ? p.summary_ar : p.summary_en }}</p>

    <ul class="effects">
      @for (effect of p.effects; track $index) {
        <li [class]="effect.direction === 'IN' ? 'in' : 'out'">
          <i [class]="effect.direction === 'IN' ? 'pi pi-arrow-down-left' : 'pi pi-arrow-up-right'" aria-hidden="true"></i>
          <span>{{ language.language() === 'ar' ? effect.label_ar : effect.label_en }}</span>
          <strong>{{ effect.direction === 'IN' ? '+' : '−' }}{{ effect.amount | money }}</strong>
        </li>
      }
    </ul>

    @for (warning of p.warnings ?? []; track $index) {
      <p-message severity="warn" data-testid="preview-warning">
        {{ 'warnings.' + warning.code | transloco: warningParams(warning.details) }}
      </p-message>
    }

    @if (p.lines) {
      <table class="lines" [attr.aria-label]="'journal.lines' | transloco">
        <thead>
          <tr>
            <th>{{ 'journal.account' | transloco }}</th>
            <th class="num">{{ 'journal.debit' | transloco }}</th>
            <th class="num">{{ 'journal.credit' | transloco }}</th>
          </tr>
        </thead>
        <tbody>
          @for (line of p.lines; track $index) {
            <tr>
              <td>{{ line.account_code }} — {{ language.language() === 'ar' ? line.account_name_ar : line.account_name_en }}</td>
              <td class="num">{{ line.debit === '0.00' ? '' : (line.debit | money) }}</td>
              <td class="num">{{ line.credit === '0.00' ? '' : (line.credit | money) }}</td>
            </tr>
          }
        </tbody>
      </table>
    }
  `,
  styles: `
    .summary {
      margin: 0 0 var(--space-3);
      font-size: 1.05rem;
      line-height: 1.7;
    }

    .effects {
      display: flex;
      flex-direction: column;
      gap: var(--space-1);
      padding: 0;
      margin: 0 0 var(--space-3);
      list-style: none;
    }

    .effects li {
      display: flex;
      gap: var(--space-2);
      align-items: center;
      padding: var(--space-2) var(--space-3);
      background: var(--color-background);
      border-radius: var(--radius);
    }

    .effects strong {
      margin-inline-start: auto;
      font-variant-numeric: tabular-nums;
    }

    .in strong {
      color: #15803d;
    }

    .out strong {
      color: var(--color-danger);
    }

    .lines {
      inline-size: 100%;
      margin-block-start: var(--space-3);
      font-size: 0.875rem;
      border-collapse: collapse;
    }

    .lines th,
    .lines td {
      padding: var(--space-1) var(--space-2);
      text-align: start;
      border-block-end: 1px solid var(--color-border);
    }

    .lines .num {
      text-align: end;
      font-variant-numeric: tabular-nums;
    }
  `,
})
export class PostingPreviewComponent {
  protected readonly language = inject(LanguageService);
  readonly preview = input.required<Preview>();

  protected readonly warningParams = (details: Record<string, unknown> | undefined) => {
    const name = this.language.language() === 'ar' ? details?.['name_ar'] : details?.['name_en'];
    return { name, balanceAfter: details?.['balance_after'] };
  };
}
