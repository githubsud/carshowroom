import { describe, expect, it } from 'vitest';

import { diffRows } from './audit.page';

describe('diffRows', () => {
  it('lists only the fields that changed, sorted', () => {
    expect(diffRows({ status: 'IN_STOCK', price: '100.00', color: 'red' }, { status: 'SOLD', price: '100.00', color: 'blue' })).toEqual([
      { field: 'color', before: 'red', after: 'blue' },
      { field: 'status', before: 'IN_STOCK', after: 'SOLD' },
    ]);
  });

  it('shows a dash for a missing side (insert and delete)', () => {
    expect(diffRows(null, { plate: 'ABC' })).toEqual([{ field: 'plate', before: '—', after: 'ABC' }]);
    expect(diffRows({ plate: 'ABC' }, undefined)).toEqual([{ field: 'plate', before: 'ABC', after: '—' }]);
  });

  it('ignores bookkeeping columns and prints nested values as JSON', () => {
    const rows = diffRows({ updated_at: '1', extra: { a: 1 } }, { updated_at: '2', extra: { a: 2 } });
    expect(rows).toEqual([{ field: 'extra', before: '{"a":1}', after: '{"a":2}' }]);
  });
});
