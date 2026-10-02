import { describe, expect, it } from 'vitest';

import { monthGrid } from './installments.page';

describe('monthGrid', () => {
  it('starts on the Monday before the 1st and covers whole weeks', () => {
    // October 2026 starts on a Thursday.
    const cells = monthGrid(2026, 10);
    expect(cells[0]).toEqual({ iso: '2026-09-28', day: 28, inMonth: false });
    expect(cells.find((c) => c.iso === '2026-10-01')?.inMonth).toBe(true);
    expect(cells.length % 7).toBe(0);
    expect(cells[cells.length - 1].iso >= '2026-10-31').toBe(true);
  });

  it('uses six weeks only when the month needs them', () => {
    expect(monthGrid(2026, 2).length).toBe(35); // February 2026: Mon 26 Jan .. Sun 1 Mar
    expect(monthGrid(2026, 3).length).toBe(42); // March 2026 starts on a Sunday
  });
});
