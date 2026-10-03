import { describe, expect, it } from 'vitest';

import { fromCents, moneyMinus, moneySum, splitByWeights, toCents } from './money-math';

describe('money maths on cents', () => {
  it('parses and prints exactly', () => {
    expect(toCents('1250000.5')).toBe(125000050n);
    expect(fromCents(125000050n)).toBe('1250000.50');
    expect(fromCents(-5n)).toBe('-0.05');
  });

  it('computes what is still to pay without floating-point error', () => {
    // 0.1 + 0.2 style traps: 100000.10 - 0.20 - 99999.90 is exactly zero.
    expect(moneyMinus('100000.10', '0.20', '99999.90')).toBe('0.00');
    expect(moneyMinus('490000', '470000', '20000')).toBe('0.00');
    expect(moneyMinus('550000.00', '350000', '')).toBe('200000.00');
  });

  it('treats empty or invalid input as zero', () => {
    expect(moneySum('10', null, undefined, 'abc', '0.5')).toBe('10.50');
  });

  it('can go negative when more is paid than owed', () => {
    expect(moneyMinus('100', '150')).toBe('-50.00');
  });
});

describe('splitByWeights', () => {
  it('splits by percentages and adds up exactly', () => {
    expect(splitByWeights('787500.00', ['60.0000', '40.0000'])).toEqual(['472500.00', '315000.00']);
    const thirds = splitByWeights('100.00', ['33.3334', '33.3333', '33.3333']);
    expect(thirds).toEqual(['33.34', '33.33', '33.33']);
    expect(splitByWeights('0.00', ['50', '50'])).toEqual(['0.00', '0.00']);
  });
});
