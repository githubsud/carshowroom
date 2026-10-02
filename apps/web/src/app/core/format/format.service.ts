import { computed, inject, Injectable, Pipe, PipeTransform } from '@angular/core';

import { LanguageService } from '../i18n/language.service';
import { TenantContextService } from '../tenant/tenant-context.service';
import { FormatOptions, formatInteger, formatMoney, formatPercent } from './money-format';

/** The single place numbers, money and dates are formatted (SPEC §9.1). */
@Injectable({ providedIn: 'root' })
export class FormatService {
  private readonly language = inject(LanguageService).language;
  private readonly context = inject(TenantContextService);

  readonly options = computed<FormatOptions>(() => ({
    language: this.language(),
    digitStyle: this.context.tenant()?.settings.digit_style ?? 'WESTERN',
  }));

  money(value: string | null | undefined, currency?: string): string {
    if (value === null || value === undefined) {
      return '—';
    }
    return formatMoney(value, currency ?? this.context.active()?.currency_code ?? '', this.options());
  }

  percent(value: string | null | undefined): string {
    return value === null || value === undefined ? '—' : formatPercent(value, this.options());
  }

  integer(value: number | null | undefined): string {
    return value === null || value === undefined ? '—' : formatInteger(value, this.options());
  }

  /** Today as YYYY-MM-DD in the showroom's timezone (the accounting date, D-18). */
  todayIso(): string {
    return new Intl.DateTimeFormat('en-CA', { timeZone: this.context.active()?.timezone }).format(new Date());
  }

  date(value: string | Date | null | undefined): string {
    if (!value) {
      return '—';
    }
    const { language, digitStyle } = this.options();
    const locale = language === 'ar' ? (digitStyle === 'ARABIC_INDIC' ? 'ar-EG' : 'ar-EG-u-nu-latn') : 'en-GB';
    return new Intl.DateTimeFormat(locale, {
      dateStyle: 'medium',
      timeZone: this.context.active()?.timezone,
    }).format(typeof value === 'string' ? new Date(value) : value);
  }
}

/** `{{ amount | money }}` — impure because it follows the language and tenant settings signals. */
@Pipe({ name: 'money', pure: false })
export class MoneyPipe implements PipeTransform {
  private readonly format = inject(FormatService);

  transform(value: string | null | undefined, currency?: string): string {
    return this.format.money(value, currency);
  }
}

@Pipe({ name: 'appDate', pure: false })
export class AppDatePipe implements PipeTransform {
  private readonly format = inject(FormatService);

  transform(value: string | Date | null | undefined): string {
    return this.format.date(value);
  }
}

@Pipe({ name: 'percent', pure: false })
export class PercentPipe implements PipeTransform {
  private readonly format = inject(FormatService);

  transform(value: string | null | undefined): string {
    return this.format.percent(value);
  }
}
