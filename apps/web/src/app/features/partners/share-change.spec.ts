import { describe, expect, it } from 'vitest';

import { fromUnits, splitEqually, toUnits } from './share-change-dialog.component';

describe('ownership percentages', () => {
  it('parses exact percentages without floating point', () => {
    expect(toUnits('33.3333')).toBe(333333);
    expect(toUnits('100')).toBe(1_000_000);
    expect(toUnits('0.0001')).toBe(1);
    expect(toUnits('12.34567')).toBeNull();
    expect(toUnits('abc')).toBeNull();
  });

  it('formats back to 4 decimals', () => {
    expect(fromUnits(333334)).toBe('33.3334');
    expect(fromUnits(1_000_000)).toBe('100.0000');
  });

  it('splits thirds as 33.3334 / 33.3333 / 33.3333 (Q-09)', () => {
    const split = splitEqually(3);
    expect(split).toEqual(['33.3334', '33.3333', '33.3333']);
    expect(split.map((s) => toUnits(s) ?? 0).reduce((a, b) => a + b, 0)).toBe(1_000_000);
  });

  it('splits evenly when it can', () => {
    expect(splitEqually(4)).toEqual(['25.0000', '25.0000', '25.0000', '25.0000']);
    expect(splitEqually(0)).toEqual([]);
  });
});
