/**
 * Display formatting for money and numbers (SPEC §3.3, §9.1).
 *
 * Money arrives from the API as a decimal string ("1250000.50"). It is
 * formatted as a string, with no conversion to a JavaScript number, so values
 * of any size stay exact. No arithmetic on money happens here.
 */

import type { DigitStyle } from '../api/api.models';
import type { Language } from '../i18n/language.service';

const ARABIC_INDIC_DIGITS = ['٠', '١', '٢', '٣', '٤', '٥', '٦', '٧', '٨', '٩'];
const MONEY_PATTERN = /^(-)?(\d+)(?:\.(\d+))?$/;

export interface FormatOptions {
  language: Language;
  digitStyle: DigitStyle;
}

export function toDigitStyle(text: string, digitStyle: DigitStyle): string {
  if (digitStyle !== 'ARABIC_INDIC') {
    return text;
  }
  return text.replace(/\d/g, (d) => ARABIC_INDIC_DIGITS[Number(d)]);
}

function separators(options: FormatOptions): { group: string; decimal: string } {
  // Arabic-Indic digits use the Arabic thousands (٬) and decimal (٫) separators.
  return options.digitStyle === 'ARABIC_INDIC' ? { group: '٬', decimal: '٫' } : { group: ',', decimal: '.' };
}

function groupThousands(integer: string, group: string): string {
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, group);
}

/** "1250000.5" → "1,250,000.50" (or "١٬٢٥٠٬٠٠٠٫٥٠"). Invalid input is returned unchanged. */
export function formatAmount(value: string, options: FormatOptions, fractionDigits = 2): string {
  const match = MONEY_PATTERN.exec(value.trim());
  if (!match) {
    return value;
  }
  const [, sign = '', integerPart, fraction = ''] = match;
  const integer = groupThousands(integerPart.replace(/^0+(?=\d)/, ''), separators(options).group);
  // Never round silently: the API sends at most 2 decimals; extra digits are shown, not dropped.
  const decimals = fraction.padEnd(fractionDigits, '0');
  const text = fractionDigits > 0 || fraction ? `${integer}${separators(options).decimal}${decimals}` : integer;
  return toDigitStyle(`${sign}${text}`, options.digitStyle);
}

const CURRENCY_LABELS: Record<string, { ar: string; en: string }> = {
  EGP: { ar: 'ج.م', en: 'EGP' },
  QAR: { ar: 'ر.ق', en: 'QAR' },
  AED: { ar: 'د.إ', en: 'AED' },
  SAR: { ar: 'ر.س', en: 'SAR' },
  SDG: { ar: 'ج.س', en: 'SDG' },
};

export function currencyLabel(currency: string, language: Language): string {
  return CURRENCY_LABELS[currency]?.[language] ?? currency;
}

/** "1250000.00", EGP → "1,250,000.00 ج.م" (ar) / "EGP 1,250,000.00" (en). */
export function formatMoney(value: string, currency: string, options: FormatOptions): string {
  const amount = formatAmount(value, options);
  const label = currencyLabel(currency, options.language);
  return options.language === 'ar' ? `${amount} ${label}` : `${label} ${amount}`;
}

/** Whole numbers (counts, days in stock). */
export function formatInteger(value: number, options: FormatOptions): string {
  return formatAmount(String(Math.trunc(value)), options, 0);
}
