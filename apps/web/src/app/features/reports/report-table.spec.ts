import { describe, expect, it } from 'vitest';

import { pickText } from './report-table.component';

describe('pickText', () => {
  it('picks the side of a bilingual cell for the language', () => {
    expect(pickText('صافي الربح|Net profit', 'ar')).toBe('صافي الربح');
    expect(pickText('صافي الربح|Net profit', 'en')).toBe('Net profit');
  });

  it('keeps plain values and empties', () => {
    expect(pickText('V-2026-0001', 'en')).toBe('V-2026-0001');
    expect(pickText(42, 'ar')).toBe('42');
    expect(pickText(null, 'ar')).toBe('');
  });
});
