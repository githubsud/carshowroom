import { FormControl } from '@angular/forms';
import { describe, expect, it } from 'vitest';

import { isValidMoney, normalizeMoneyInput, positiveMoney } from './money-input';

describe('normalizeMoneyInput', () => {
  it('converts Arabic-Indic and Persian digits and the Arabic decimal mark', () => {
    expect(normalizeMoneyInput('٢٥٠٠٠٫٥٠')).toBe('25000.50');
    expect(normalizeMoneyInput('۱۲۳')).toBe('123');
  });

  it('drops thousands separators and spaces', () => {
    expect(normalizeMoneyInput(' 25,000.00 ')).toBe('25000.00');
    expect(normalizeMoneyInput('١٬٢٥٠')).toBe('1250');
  });
});

describe('money validation', () => {
  it('accepts plain amounts with up to 2 decimals', () => {
    for (const value of ['0.01', '25000', '25000.5', '9999999999999999.99']) {
      expect(isValidMoney(value)).toBe(true);
    }
  });

  it('rejects more decimals, signs, exponents and garbage', () => {
    for (const value of ['10.005', '-5', '1e3', 'abc', '', '.5', '10.']) {
      expect(isValidMoney(value)).toBe(false);
    }
  });

  it('requires a positive amount', () => {
    expect(positiveMoney(new FormControl('0.00'))).toEqual({ positive: true });
    expect(positiveMoney(new FormControl('12.345'))).toEqual({ money: true });
    expect(positiveMoney(new FormControl('12.34'))).toBeNull();
    expect(positiveMoney(new FormControl(''))).toBeNull();
  });
});
