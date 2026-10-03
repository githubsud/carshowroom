import { Component, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ReportColumn, ReportRow, ReportTable } from '../../core/api/api.models';
import { MoneyPipe } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { TenantContextService } from '../../core/tenant/tenant-context.service';

/** A cell may carry "عربي|English": the language picks its side. */
export function pickText(value: string | number | null | undefined, language: 'ar' | 'en'): string {
  if (value === null || value === undefined) {
    return '';
  }
  const raw = String(value);
  const pipe = raw.indexOf('|');
  if (pipe < 0) {
    return raw;
  }
  return language === 'ar' ? raw.slice(0, pipe) : raw.slice(pipe + 1);
}

/**
 * Renders any report of the reports centre (the API's ReportTable): headline
 * figures, then the table. Text may carry "عربي|English"; the active language
 * picks its side.
 */
@Component({
  selector: 'app-report-table',
  imports: [RouterLink, MoneyPipe],
  template: `
    @if (table(); as t) {
      @if (t.figures?.length) {
        <div class="figures card" data-testid="report-figures">
          @for (f of t.figures; track $index) {
            <div class="figure">
              <span>{{ ar() ? f[0] : f[1] }}</span>
              <strong>{{ f[3] === 'money' ? (f[2] | money: t.currency_code) : f[2] }}</strong>
            </div>
          }
        </div>
      }
      <div class="table-wrap">
        <table class="report" data-testid="report-table">
          <thead>
            <tr>
              @for (c of t.columns; track c.key) {
                <th [class.num]="numeric(c)">{{ ar() ? c.label_ar : c.label_en }}</th>
              }
            </tr>
          </thead>
          <tbody>
            @for (row of t.rows; track $index) {
              <tr [class]="row.style ?? ''">
                @for (c of t.columns; track c.key; let first = $first) {
                  <td [class.num]="numeric(c)">
                    @if (first && row.link) {
                      <a [routerLink]="['/t', context.activeTenantId(), ...row.link]">{{ text(row, c) }}</a>
                    } @else if (c.kind === 'money') {
                      {{ row.cells[c.key] === null || row.cells[c.key] === undefined ? '' : (asString(row.cells[c.key]) | money: t.currency_code) }}
                    } @else {
                      {{ text(row, c) }}
                    }
                  </td>
                }
              </tr>
            } @empty {
              <tr><td [attr.colspan]="t.columns.length" class="empty">—</td></tr>
            }
          </tbody>
        </table>
      </div>
    }
  `,
  styles: `
    .table-wrap {
      overflow-x: auto;
    }
    .report {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;

      th {
        padding: var(--space-2);
        text-align: start;
        white-space: nowrap;
        background: var(--color-surface-muted, #f1f5f9);
      }
      td {
        padding: var(--space-1) var(--space-2);
        border-block-end: 1px solid var(--color-border);
      }
      .num {
        text-align: end;
        white-space: nowrap;
      }
      tr.total td {
        font-weight: 700;
        border-block-start: 2px solid var(--color-text);
      }
      tr.section td {
        font-weight: 700;
        background: var(--color-surface-muted, #f8fafc);
      }
      tr.muted td {
        color: var(--color-text-muted);
      }
      .empty {
        text-align: center;
      }
    }
  `,
})
export class ReportTableComponent {
  private readonly language = inject(LanguageService);
  protected readonly context = inject(TenantContextService);

  readonly table = input<ReportTable | null>(null);

  protected ar(): boolean {
    return this.language.language() === 'ar';
  }

  protected numeric(column: ReportColumn): boolean {
    return column.kind === 'money' || column.kind === 'number' || column.kind === 'percent';
  }

  protected asString(value: unknown): string {
    return String(value);
  }

  protected text(row: ReportRow, column: ReportColumn): string {
    const shown = pickText(row.cells[column.key], this.language.language());
    return column.kind === 'percent' && shown ? `${shown}%` : shown;
  }
}
