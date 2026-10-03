import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';

import { TenantSettings } from '../../core/api/api.models';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { ErrorMessageService } from '../../shared/error-message.service';
import { loaded, translationsLoaded } from '../../shared/translated';

type Choice = keyof Pick<
  TenantSettings,
  | 'profit_policy'
  | 'distribution_frequency'
  | 'loss_handling'
  | 'prorata_method'
  | 'rounding_remainder'
  | 'sale_cancellation_method'
  | 'overpayment_policy'
  | 'cash_negative_policy'
>;

const CHOICES: Record<Choice, readonly string[]> = {
  profit_policy: ['PERIODIC', 'PER_CAR'],
  distribution_frequency: ['AD_HOC', 'MONTHLY', 'QUARTERLY', 'YEARLY'],
  loss_handling: ['ALLOCATE_TO_PARTNERS', 'CARRY_FORWARD'],
  prorata_method: ['DAY_WEIGHTED', 'SUB_PERIOD_PROFIT'],
  rounding_remainder: ['LARGEST_REMAINDER', 'LARGEST_SHARE'],
  sale_cancellation_method: ['REFUND_LIABILITY', 'MIRROR'],
  overpayment_policy: ['BLOCK', 'ALLOW_AS_CREDIT'],
  cash_negative_policy: ['WARN', 'BLOCK'],
};

/** Settings → Policies (D-40, D-41): how profit is distributed, how sales are cancelled, aging colours. */
@Component({
  selector: 'app-policies-page',
  imports: [FormsModule, TranslocoPipe, ButtonModule, CheckboxModule, InputTextModule, SelectModule],
  template: `
    <div class="page-header"><h1 class="page-title">{{ 'policies.title' | transloco }}</h1></div>
    <section class="card dialog-fields" data-testid="policies">
      @for (key of keys; track key) {
        <div class="field">
          <label [for]="'pol-' + key">{{ 'policies.' + key | transloco }}</label>
          <p-select [inputId]="'pol-' + key" [options]="options()[key]" [(ngModel)]="values[key]" optionLabel="label"
                    optionValue="value" [fluid]="true" />
          <small class="sub">{{ 'policies.' + key + '_hint' | transloco }}</small>
        </div>
      }
      <div class="field">
        <span>{{ 'policies.aging' | transloco }}</span>
        <div class="row">
          @for (i of [0, 1, 2]; track i) {
            <input pInputText type="number" inputmode="numeric" [(ngModel)]="aging[i]"
                   [attr.aria-label]="('policies.aging' | transloco) + ' ' + (i + 1)" />
          }
        </div>
      </div>
      <span class="check"><p-checkbox [(ngModel)]="partnerSeesSummary" [binary]="true" inputId="pol-summary" />
        <label for="pol-summary">{{ 'policies.partner_sees_summary' | transloco }}</label></span>
      <p-button [label]="'settings.save' | transloco" (onClick)="save()" [loading]="busy()" data-testid="policies-save" />
    </section>
  `,
  styles: `
    .check {
      display: flex;
      gap: var(--space-2);
      align-items: center;
    }
  `,
})
export class PoliciesPage implements OnInit {
  private readonly context = inject(TenantContextService);
  private readonly transloco = inject(TranslocoService);
  private readonly toast = inject(MessageService);
  private readonly errors = inject(ErrorMessageService);
  private readonly translations = translationsLoaded();

  protected readonly keys = Object.keys(CHOICES) as Choice[];
  protected readonly busy = signal(false);
  protected values = {} as Record<Choice, string>;
  protected aging: number[] = [30, 60, 90];
  protected partnerSeesSummary = false;

  protected readonly options = computed(() => {
    const ready = loaded(this.translations());
    return Object.fromEntries(
      this.keys.map((key) => [
        key,
        ready ? CHOICES[key].map((value) => ({ value, label: this.transloco.translate(`policies.${key}_${value}`) })) : [],
      ]),
    ) as Record<Choice, { value: string; label: string }[]>;
  });

  ngOnInit(): void {
    const settings = this.context.tenant()?.settings;
    if (settings) {
      this.values = Object.fromEntries(this.keys.map((key) => [key, settings[key]])) as Record<Choice, string>;
      this.aging = [...settings.aging_thresholds];
      this.partnerSeesSummary = settings.partner_sees_summary;
    }
  }

  protected async save(): Promise<void> {
    this.busy.set(true);
    try {
      await this.context.updateSettings({
        ...(this.values as Partial<TenantSettings>),
        aging_thresholds: this.aging.map(Number),
        partner_sees_summary: this.partnerSeesSummary,
      });
      this.toast.add({ severity: 'success', summary: this.transloco.translate('settings.saved') });
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    } finally {
      this.busy.set(false);
    }
  }
}
