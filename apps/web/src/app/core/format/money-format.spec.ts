import { describe, expect, it } from 'vitest';

import { currencyLabel, formatAmount, formatInteger, formatMoney, formatPercent, ltr, toDigitStyle } from './money-format';

const western = { language: 'en', digitStyle: 'WESTERN' } as const;
const arabicWestern = { language: 'ar', digitStyle: 'WESTERN' } as const;
const arabicIndic = { language: 'ar', digitStyle: 'ARABIC_INDIC' } as const;

describe('formatAmount', () => {
  it('groups thousands and pads to two decimals', () => {
    expect(formatAmount('1250000.5', western)).toBe('1,250,000.50');
    expect(formatAmount('0', western)).toBe('0.00');
    expect(formatAmount('999', western)).toBe('999.00');
  });

  it('keeps values beyond JavaScript number precision exact', () => {
    // 16 integer digits: a float would turn this into 9999999999999998.00
    expect(formatAmount('9999999999999999.99', western)).toBe('9,999,999,999,999,999.99');
  });

  it('handles negatives and leading zeros', () => {
    expect(formatAmount('-50000.00', western)).toBe('-50,000.00');
    expect(formatAmount('000123.40', western)).toBe('123.40');
  });

  it('never rounds silently', () => {
    expect(formatAmount('10.005', western)).toBe('10.005');
  });

  it('uses Arabic-Indic digits and separators when the tenant asks for them', () => {
    expect(formatAmount('1250000.50', arabicIndic)).toBe('١٬٢٥٠٬٠٠٠٫٥٠');
  });

  it('returns unparsable input unchanged', () => {
    expect(formatAmount('abc', western)).toBe('abc');
    expect(formatAmount('1e5', western)).toBe('1e5');
  });
});

describe('formatMoney', () => {
  it('places the currency after the amount in Arabic and before it in English', () => {
    expect(formatMoney('50000', 'EGP', arabicWestern)).toBe(`${ltr('50,000.00')} ج.م`);
    expect(formatMoney('50000', 'EGP', western)).toBe('EGP 50,000.00');
    expect(formatMoney('50000', 'QAR', arabicIndic)).toBe(`${ltr('٥٠٬٠٠٠٫٠٠')} ر.ق`);
  });

  it('keeps the minus sign in front of the digits inside Arabic text', () => {
    expect(formatMoney('-2000', 'EGP', arabicWestern)).toBe('\u2066-2,000.00\u2069 ج.م');
  });

  it('falls back to the ISO code for unknown currencies', () => {
    expect(currencyLabel('XYZ', 'ar')).toBe('XYZ');
  });
});

describe('formatPercent', () => {
  it('drops trailing zeros and keeps needed decimals', () => {
    expect(formatPercent('50.0000', western)).toBe(ltr('50%'));
    expect(formatPercent('33.3334', western)).toBe(ltr('33.3334%'));
    expect(formatPercent('12.5000', arabicIndic)).toBe(ltr('١٢٫٥%'));
  });
});

describe('integers and digits', () => {
  it('formats counts without decimals', () => {
    expect(formatInteger(1234, western)).toBe('1,234');
    expect(formatInteger(45, arabicIndic)).toBe('٤٥');
  });

  it('converts digits only when requested', () => {
    expect(toDigitStyle('2026-10-02', 'WESTERN')).toBe('2026-10-02');
    expect(toDigitStyle('2026', 'ARABIC_INDIC')).toBe('٢٠٢٦');
  });
});
