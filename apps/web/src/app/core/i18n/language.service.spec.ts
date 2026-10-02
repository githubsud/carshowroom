import { TestBed } from '@angular/core/testing';
import { TranslocoService } from '@jsverse/transloco';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { directionOf, LanguageService } from './language.service';

describe('LanguageService', () => {
  const transloco = { setActiveLang: vi.fn() };

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [{ provide: TranslocoService, useValue: transloco }] });
  });

  it('defaults to Arabic, right-to-left', () => {
    TestBed.inject(LanguageService);
    TestBed.tick();
    expect(document.documentElement.lang).toBe('ar');
    expect(document.documentElement.dir).toBe('rtl');
    expect(transloco.setActiveLang).toHaveBeenLastCalledWith('ar');
  });

  it('switches to English, left-to-right, and remembers the choice', () => {
    const service = TestBed.inject(LanguageService);
    service.toggle();
    TestBed.tick();
    expect(document.documentElement.lang).toBe('en');
    expect(document.documentElement.dir).toBe('ltr');
    expect(localStorage.getItem('sayyara.language')).toBe('en');
  });

  it("lets the user's own choice win over the tenant default", () => {
    const service = TestBed.inject(LanguageService);
    service.set('en');
    service.applyTenantDefault('ar');
    expect(service.language()).toBe('en');
  });

  it('applies the tenant default when the user has not chosen', () => {
    const service = TestBed.inject(LanguageService);
    service.applyTenantDefault('en');
    expect(service.language()).toBe('en');
  });

  it('maps languages to directions', () => {
    expect(directionOf('ar')).toBe('rtl');
    expect(directionOf('en')).toBe('ltr');
  });
});
