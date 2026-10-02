import { describe, expect, it } from 'vitest';

import { fitWithin } from './image-compress';

describe('fitWithin', () => {
  it('scales a landscape phone photo so the longest edge is 1600 px', () => {
    expect(fitWithin(4032, 3024)).toEqual({ width: 1600, height: 1200 });
  });

  it('scales portrait photos by their height', () => {
    expect(fitWithin(3000, 4000)).toEqual({ width: 1200, height: 1600 });
  });

  it('never enlarges a small image', () => {
    expect(fitWithin(800, 600)).toEqual({ width: 800, height: 600 });
  });
});
