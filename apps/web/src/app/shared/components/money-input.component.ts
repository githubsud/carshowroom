import { Component, computed, forwardRef, inject, input, signal } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';
import { InputTextModule } from 'primeng/inputtext';

import { currencyLabel } from '../../core/format/money-format';
import { LanguageService } from '../../core/i18n/language.service';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { normalizeMoneyInput } from '../money-input';

/**
 * Amount field: numeric keypad on phones, accepts Arabic-Indic digits, emits a
 * normalised decimal string. Pair with the positiveMoney validator.
 */
@Component({
  selector: 'app-money-input',
  imports: [InputTextModule],
  providers: [{ provide: NG_VALUE_ACCESSOR, useExisting: forwardRef(() => MoneyInputComponent), multi: true }],
  template: `
    <div class="money">
      <input
        pInputText
        type="text"
        inputmode="decimal"
        autocomplete="off"
        dir="ltr"
        [id]="inputId()"
        [value]="text()"
        [disabled]="disabled()"
        [attr.aria-label]="ariaLabel()"
        (input)="onInput($event)"
        (blur)="touched()"
      />
      <span class="currency">{{ currency() }}</span>
    </div>
  `,
  styles: `
    .money {
      display: flex;
      gap: var(--space-2);
      align-items: center;
    }

    input {
      flex: 1;
      font-variant-numeric: tabular-nums;
      text-align: end;
    }

    .currency {
      color: var(--color-text-muted);
      white-space: nowrap;
    }
  `,
})
export class MoneyInputComponent implements ControlValueAccessor {
  private readonly context = inject(TenantContextService);
  private readonly language = inject(LanguageService).language;

  readonly inputId = input<string>('');
  readonly ariaLabel = input<string | null>(null);

  protected readonly text = signal('');
  protected readonly disabled = signal(false);
  protected readonly currency = computed(() =>
    currencyLabel(this.context.active()?.currency_code ?? '', this.language()),
  );

  private onChange: (value: string) => void = () => undefined;
  protected touched: () => void = () => undefined;

  writeValue(value: string | null): void {
    this.text.set(value ?? '');
  }

  registerOnChange(fn: (value: string) => void): void {
    this.onChange = fn;
  }

  registerOnTouched(fn: () => void): void {
    this.touched = fn;
  }

  setDisabledState(disabled: boolean): void {
    this.disabled.set(disabled);
  }

  protected onInput(event: Event): void {
    const raw = (event.target as HTMLInputElement).value;
    this.text.set(raw);
    this.onChange(normalizeMoneyInput(raw));
  }
}
