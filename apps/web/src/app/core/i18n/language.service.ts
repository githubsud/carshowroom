import { DOCUMENT } from '@angular/common';
import { effect, inject, Injectable, signal } from '@angular/core';
import { TranslocoService } from '@jsverse/transloco';

export type Language = 'ar' | 'en';

const LANGUAGE_KEY = 'sayyara.language';

export function directionOf(language: Language): 'rtl' | 'ltr' {
  return language === 'ar' ? 'rtl' : 'ltr';
}

/**
 * Runtime language switching (SPEC §2): Arabic (default, RTL) and English (LTR).
 * Sets `lang` and `dir` on <html>; all styles use logical properties, so the
 * layout mirrors without per-language CSS.
 */
@Injectable({ providedIn: 'root' })
export class LanguageService {
  private readonly document = inject(DOCUMENT);
  private readonly transloco = inject(TranslocoService);

  private readonly _language = signal<Language>(this.stored() ?? 'ar');
  readonly language = this._language.asReadonly();

  constructor() {
    effect(() => {
      const language = this._language();
      const html = this.document.documentElement;
      html.lang = language;
      html.dir = directionOf(language);
      this.transloco.setActiveLang(language);
    });
  }

  set(language: Language): void {
    this._language.set(language);
    try {
      localStorage.setItem(LANGUAGE_KEY, language);
    } catch {
      // Remembering the choice is a convenience only.
    }
  }

  toggle(): void {
    this.set(this._language() === 'ar' ? 'en' : 'ar');
  }

  /** The user's own choice wins over the tenant default. */
  applyTenantDefault(language: Language): void {
    if (!this.stored()) {
      this._language.set(language);
    }
  }

  private stored(): Language | null {
    try {
      const value = localStorage.getItem(LANGUAGE_KEY);
      return value === 'ar' || value === 'en' ? value : null;
    } catch {
      return null;
    }
  }
}
