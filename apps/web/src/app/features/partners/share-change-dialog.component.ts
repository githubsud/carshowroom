import { Component, computed, effect, inject, input, model, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';

import { Partner, Share } from '../../core/api/api.models';
import { FormatService } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { ErrorMessageService } from '../../shared/error-message.service';
import { normalizeMoneyInput } from '../../shared/money-input';
import { PartnersService } from './partners.service';

const PERCENT = /^\d{1,3}(\.\d{1,4})?$/;

/** Percentages are exact decimals; compare in ten-thousandths, never as floats. */
export function toUnits(value: string): number | null {
  if (!PERCENT.test(value)) {
    return null;
  }
  const [whole, fraction = ''] = value.split('.');
  return Number(whole) * 10000 + Number(fraction.padEnd(4, '0'));
}

export function fromUnits(units: number): string {
  return `${Math.trunc(units / 10000)}.${String(units % 10000).padStart(4, '0')}`;
}

/** Split 100% equally; the 0.0001 remainder goes to the first partner (DECISIONS Q-09). */
export function splitEqually(count: number): string[] {
  if (count === 0) {
    return [];
  }
  const each = Math.floor(1_000_000 / count);
  return Array.from({ length: count }, (_, i) => fromUnits(i === 0 ? 1_000_000 - each * (count - 1) : each));
}

interface Row {
  partner: Partner;
  percentage: string;
}

/** Record a new ownership batch from a date (D-21): must total exactly 100%. */
@Component({
  selector: 'app-share-change-dialog',
  imports: [FormsModule, TranslocoPipe, ButtonModule, DialogModule, InputTextModule, MessageModule],
  template: `
    <p-dialog [visible]="visible()" (visibleChange)="visible.set($event)" [modal]="true"
              [header]="'partners.sharesTitle' | transloco" [style]="{ width: 'min(520px, 96vw)' }">
      <p class="hint">{{ 'partners.sharesHint' | transloco }}</p>
      <div class="field">
        <label for="effective">{{ 'partners.effectiveFrom' | transloco }}</label>
        <input pInputText id="effective" type="date" [(ngModel)]="effectiveFrom" data-testid="shares-date" />
      </div>
      <table class="shares">
        <tbody>
          @for (row of rows(); track row.partner.id; let i = $index) {
            <tr>
              <td>{{ name(row.partner) }}</td>
              <td class="pct">
                <input pInputText inputmode="decimal" dir="ltr" [ngModel]="row.percentage"
                       (ngModelChange)="setPercentage(i, $event)" [attr.data-testid]="'share-' + i" />
                <span>%</span>
              </td>
            </tr>
          }
        </tbody>
        <tfoot>
          <tr [class.bad]="!valid()">
            <td>{{ 'partners.total' | transloco }}</td>
            <td class="pct" data-testid="shares-total">{{ total() }}%</td>
          </tr>
        </tfoot>
      </table>
      <p-button [text]="true" icon="pi pi-equals" [label]="'partners.splitEqually' | transloco" (onClick)="equal()" />
      @if (error()) {
        <p-message severity="error">{{ error() }}</p-message>
      }
      <div class="actions">
        <p-button [text]="true" [label]="'common.cancel' | transloco" (onClick)="visible.set(false)" />
        <p-button data-testid="shares-save" [label]="'settings.save' | transloco" [disabled]="!valid() || !effectiveFrom"
                  [loading]="busy()" (onClick)="save()" />
      </div>
    </p-dialog>
  `,
  styles: `
    .hint {
      margin-block-start: 0;
      color: var(--color-text-muted);
    }

    .field {
      display: flex;
      flex-direction: column;
      gap: var(--space-1);
      margin-block-end: var(--space-3);
    }

    .shares {
      inline-size: 100%;
      border-collapse: collapse;

      td {
        padding: var(--space-1) 0;
        border-block-end: 1px solid var(--color-border);
      }

      tfoot td {
        font-weight: 700;
      }

      .bad td {
        color: var(--color-danger);
      }
    }

    .pct {
      display: flex;
      gap: var(--space-1);
      align-items: center;
      justify-content: flex-end;

      input {
        inline-size: 7rem;
        text-align: end;
      }
    }

    .actions {
      display: flex;
      gap: var(--space-2);
      justify-content: flex-end;
      margin-block-start: var(--space-3);
    }
  `,
})
export class ShareChangeDialogComponent {
  private readonly api = inject(PartnersService);
  private readonly errors = inject(ErrorMessageService);
  private readonly format = inject(FormatService);
  private readonly language = inject(LanguageService);

  readonly visible = model(false);
  readonly partners = input.required<Partner[]>();
  readonly current = input<Share[]>([]);
  readonly saved = output<void>();

  protected readonly rows = signal<Row[]>([]);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected effectiveFrom = '';

  protected readonly units = computed(() => this.rows().map((r) => toUnits(r.percentage || '0')));
  protected readonly total = computed(() =>
    this.units().some((u) => u === null) ? '—' : fromUnits(this.units().reduce<number>((s, u) => s + (u ?? 0), 0)),
  );
  protected readonly valid = computed(() => this.total() === '100.0000');

  constructor() {
    effect(() => {
      if (this.visible()) {
        const byPartner = new Map(this.current().map((s) => [s.partner_id, s.percentage]));
        this.rows.set(this.partners().map((partner) => ({ partner, percentage: byPartner.get(partner.id) ?? '0' })));
        this.effectiveFrom = this.format.todayIso();
        this.error.set(null);
      }
    });
  }

  protected name(partner: Partner): string {
    return this.language.language() === 'ar' ? partner.name_ar : (partner.name_en ?? partner.name_ar);
  }

  protected setPercentage(index: number, raw: string): void {
    const value = normalizeMoneyInput(raw);
    this.rows.update((rows) => rows.map((r, i) => (i === index ? { ...r, percentage: value } : r)));
  }

  protected equal(): void {
    const split = splitEqually(this.rows().length);
    this.rows.update((rows) => rows.map((r, i) => ({ ...r, percentage: split[i] })));
  }

  protected async save(): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      await this.api.changeShares({
        effective_from: this.effectiveFrom,
        shares: this.rows()
          .filter((r) => (toUnits(r.percentage) ?? 0) > 0)
          .map((r) => ({ partner_id: r.partner.id, percentage: r.percentage })),
      });
      this.visible.set(false);
      this.saved.emit();
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }
}
