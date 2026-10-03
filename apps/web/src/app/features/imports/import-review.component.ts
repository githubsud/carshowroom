import { Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { MessageModule } from 'primeng/message';
import { SelectModule } from 'primeng/select';
import { TagModule } from 'primeng/tag';

import { ImportJob, ImportKind, ImportPosting, ImportSheet } from '../../core/api/api.models';
import { MoneyPipe } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { saveBlob } from '../../shared/download';
import { ErrorMessageService } from '../../shared/error-message.service';
import { loaded, translationsLoaded } from '../../shared/translated';
import { ImportsService } from './imports.service';

const KINDS: ImportKind[] = ['VEHICLES', 'CUSTOMERS', 'PARTNERS', 'INSTALLMENTS', 'CASH'];

interface SheetDraft {
  kind: ImportKind;
  skip: boolean;
  map: (string | null)[];
}

/**
 * Map each sheet's columns, check every row (nothing is saved), then import
 * everything at once with one opening entry (BACKLOG 8.2-8.4).
 */
@Component({
  selector: 'app-import-review',
  imports: [FormsModule, TranslocoPipe, ButtonModule, CheckboxModule, MessageModule, SelectModule, TagModule, MoneyPipe],
  template: `
    @if (job(); as j) {
      @for (sheet of j.sheets; track sheet.index) {
        <section class="card sheet" [attr.data-testid]="'sheet-' + sheet.index">
          <div class="sheet-head">
            <h2>{{ sheet.name }} <small>({{ 'imports.rows' | transloco: { n: sheet.row_count } }})</small></h2>
            <p-select [options]="kindOptions()" [(ngModel)]="drafts[sheet.index].kind" (ngModelChange)="kindChanged(sheet)"
                      optionLabel="label" optionValue="value" [attr.aria-label]="'imports.kind' | transloco"
                      [attr.data-testid]="'sheet-kind-' + sheet.index" />
            <span class="check"><p-checkbox [(ngModel)]="drafts[sheet.index].skip" [binary]="true" [inputId]="'skip-' + sheet.index" />
              <label [for]="'skip-' + sheet.index">{{ 'imports.skip' | transloco }}</label></span>
            @if (sheet.mapping_remembered) { <p-tag severity="info" [value]="'imports.remembered' | transloco" /> }
          </div>
          @if (!drafts[sheet.index].skip) {
            <div class="table-wrap">
              <table class="map">
                <thead>
                  <tr>
                    @for (header of sheet.headers; track $index) {
                      <th>
                        <div class="header">{{ header }}</div>
                        <select [(ngModel)]="drafts[sheet.index].map[$index]" [attr.aria-label]="header"
                                [attr.data-testid]="'map-' + sheet.index + '-' + $index">
                          <option [ngValue]="null">— {{ 'imports.ignore' | transloco }} —</option>
                          @for (f of fieldsFor(drafts[sheet.index].kind); track f.key) {
                            <option [ngValue]="f.key">{{ ar() ? f.label_ar : f.label_en }}{{ f.required ? ' *' : '' }}</option>
                          }
                        </select>
                      </th>
                    }
                  </tr>
                </thead>
                <tbody>
                  @for (row of sheet.sample_rows; track $index) {
                    <tr>@for (cell of row; track $index) { <td>{{ cell }}</td> }</tr>
                  }
                </tbody>
              </table>
            </div>
          }
          @if (sheet.ok_rows !== null && sheet.ok_rows !== undefined && !drafts[sheet.index].skip) {
            <p class="result" [class.negative]="sheet.error_rows?.length" [attr.data-testid]="'result-' + sheet.index">
              {{ 'imports.okRows' | transloco: { n: sheet.ok_rows } }}
              @if (sheet.error_rows?.length) { · {{ 'imports.errorRows' | transloco: { n: sheet.error_rows?.length } }} }
            </p>
            @if (sheet.error_rows?.length) {
              <ul class="errors" [attr.data-testid]="'errors-' + sheet.index">
                @for (r of sheet.error_rows; track $index) {
                  <li>
                    <strong>{{ r.row_no ? ('imports.row' | transloco: { n: r.row_no }) : ('imports.sheet' | transloco) }}</strong>:
                    @for (e of r.errors; track $index) {
                      <span>{{ fieldLabel(drafts[sheet.index].kind, e.field) }} {{ 'imports.error_' + e.code | transloco }}</span>
                    }
                  </li>
                }
              </ul>
            }
          }
        </section>
      }

      @if (error()) { <p-message severity="error" data-testid="import-error">{{ error() }}</p-message> }
      <div class="actions">
        <p-button icon="pi pi-check-square" [label]="'imports.check' | transloco" (onClick)="check()" [loading]="busy()"
                  data-testid="import-check" />
        @if (j.status === 'VALIDATED' && hasErrors()) {
          <p-button icon="pi pi-download" severity="secondary" [label]="'imports.errorFile' | transloco" (onClick)="errorFile()" />
        }
        @if (j.status === 'VALIDATED' && !hasErrors()) {
          <span class="total">{{ 'imports.openingTotal' | transloco }} <strong>{{ j.opening_total | money }}</strong></span>
          <p-button icon="pi pi-cloud-upload" [label]="'imports.commit' | transloco" (onClick)="commit()" [loading]="busy()"
                    data-testid="import-commit" />
        }
      </div>
    }
  `,
  styles: `
    .sheet-head {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      align-items: center;

      h2 {
        margin: 0;
        margin-inline-end: auto;
      }
      small {
        font-weight: 400;
        color: var(--color-text-muted);
      }
    }
    .check {
      display: flex;
      gap: var(--space-1);
      align-items: center;
    }
    .table-wrap {
      margin-block: var(--space-2);
      overflow-x: auto;
    }
    .map {
      border-collapse: collapse;
      font-size: 0.85rem;

      th,
      td {
        padding: var(--space-1);
        white-space: nowrap;
        border: 1px solid var(--color-border);
      }
      th {
        vertical-align: top;
        background: var(--color-surface-muted, #f1f5f9);
      }
      .header {
        margin-block-end: 4px;
      }
      select {
        max-inline-size: 150px;
        font: inherit;
      }
    }
    .errors {
      max-block-size: 260px;
      padding-inline-start: var(--space-4);
      overflow-y: auto;
      color: var(--color-danger);

      span + span::before {
        content: '، ';
      }
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      align-items: center;
    }
    .total {
      margin-inline-start: auto;
    }
  `,
})
export class ImportReviewComponent {
  private readonly api = inject(ImportsService);
  private readonly errors = inject(ErrorMessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly language = inject(LanguageService);
  private readonly translations = translationsLoaded();

  readonly job = input.required<ImportJob>();
  readonly changed = output<ImportJob>();
  readonly committed = output<ImportPosting>();

  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected drafts: SheetDraft[] = [];
  private key = crypto.randomUUID();

  protected readonly kindOptions = computed(() =>
    loaded(this.translations())
      ? KINDS.map((value) => ({ value, label: this.transloco.translate(`imports.kind_${value}`) }))
      : [],
  );
  protected readonly hasErrors = computed(() => this.job().sheets.some((s) => !s.skip && (s.error_rows?.length ?? 0) > 0));

  constructor() {
    effect(() => {
      this.drafts = this.job().sheets.map((s) => ({ kind: s.kind, skip: s.skip, map: [...s.column_map] }));
    });
  }

  protected ar(): boolean {
    return this.language.language() === 'ar';
  }

  protected fieldsFor(kind: ImportKind) {
    return this.job().fields[kind] ?? [];
  }

  protected fieldLabel(kind: ImportKind, key: string | null | undefined): string {
    if (!key) {
      return '';
    }
    const spec = this.fieldsFor(kind).find((f) => f.key === key);
    return spec ? `${this.ar() ? spec.label_ar : spec.label_en}:` : `${key}:`;
  }

  protected kindChanged(sheet: ImportSheet): void {
    // Another kind: start from no mapping (the server suggests one after saving).
    this.drafts[sheet.index].map = sheet.headers.map(() => null);
  }

  protected async check(): Promise<void> {
    await this.run(async () => {
      await this.api.setMapping(this.job().id, {
        sheets: this.drafts.map((d, index) => ({ index, kind: d.kind, column_map: d.map, skip: d.skip, remember: true })),
      });
      const checked = await this.api.validate(this.job().id);
      this.key = crypto.randomUUID();
      this.changed.emit(checked);
    });
  }

  protected async commit(): Promise<void> {
    await this.run(async () => this.committed.emit(await this.api.commit(this.job().id, this.key)));
  }

  protected async errorFile(): Promise<void> {
    await this.run(async () => saveBlob(await this.api.errors(this.job().id, this.language.language()), 'import-errors.xlsx'));
  }

  private async run(action: () => Promise<void>): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      await action();
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }
}
