import { Component, computed, inject, input } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

import { FormatService } from '../../core/format/format.service';

/** The example car profit used to explain the rules in plain words. */
const EXAMPLE_PROFIT = 50000;
const EXAMPLE_SHARE = 40;

/**
 * “How a partner's profit is worked out” in plain words with a worked example
 * (pilot feedback 2026-10-25): the showroom's chosen policies, applied to one
 * partner's share when given, otherwise to an example share.
 */
@Component({
  selector: 'app-profit-rules',
  imports: [TranslocoPipe],
  template: `
    <section class="card rules" data-testid="profit-rules">
      <h2>
        <i class="pi pi-info-circle" aria-hidden="true"></i> {{ 'profitRules.title' | transloco }}
      </h2>
      <ul>
        <li>
          {{
            (percentage() === null ? 'profitRules.kindExample' : 'profitRules.kind')
              | transloco: { share: share() }
          }}
        </li>
        <li>{{ 'profitRules.' + policy() | transloco: example() }}</li>
        <li>{{ 'profitRules.expenses_' + policy() | transloco }}</li>
        <li>{{ 'profitRules.loss_' + lossHandling() | transloco: { share: share() } }}</li>
        <li class="sharia">{{ 'profitRules.sharia' | transloco }}</li>
      </ul>
    </section>
  `,
  styles: `
    .rules {
      margin-block-end: var(--space-3);
    }
    h2 {
      display: flex;
      gap: var(--space-2);
      align-items: center;
      font-size: 1rem;
    }
    ul {
      display: grid;
      gap: var(--space-2);
      padding-inline-start: var(--space-4);
      margin: 0;
    }
    .sharia {
      color: var(--color-text-muted);
    }
  `,
})
export class ProfitRulesComponent {
  private readonly format = inject(FormatService);

  /** The showroom's choices (saved, or still being edited on the policies page). */
  readonly settings = input.required<{ profit_policy: string; loss_handling: string }>();
  /** The partner's current ownership share (e.g. "40.0000"); an example share when absent. */
  readonly percentage = input<string | null>(null);

  protected readonly policy = computed(() => this.settings().profit_policy);
  protected readonly lossHandling = computed(() => this.settings().loss_handling);
  private readonly shareNumber = computed(() => {
    const value = Number(this.percentage());
    return this.percentage() !== null && Number.isFinite(value) ? value : EXAMPLE_SHARE;
  });
  protected readonly share = computed(() => this.format.percent(String(this.shareNumber())));
  protected readonly example = computed(() => ({
    share: this.share(),
    profit: this.format.money(EXAMPLE_PROFIT.toFixed(2)),
    part: this.format.money(((EXAMPLE_PROFIT * this.shareNumber()) / 100).toFixed(2)),
  }));
}
