import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, inject, isDevMode, provideAppInitializer, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { provideTransloco } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { providePrimeNG } from 'primeng/config';

import { routes } from './app.routes';
import { apiInterceptor } from './core/http/api.interceptor';
import { LanguageService } from './core/i18n/language.service';
import { TranslocoHttpLoader } from './core/i18n/transloco.loader';
import { SayyaraPreset } from './core/theme/theme';

/**
 * PrimeUI licence key (DECISIONS Q-38, D-61). Injected at build time with
 * `--define PRIMEUI_LICENSE="'<key>'"` from the PRIMEUI_LICENSE environment
 * variable (scripts/dev.ps1, Makefile, CI); never committed.
 */
declare const PRIMEUI_LICENSE: string | undefined;
const primeuiLicense = typeof PRIMEUI_LICENSE === 'string' && PRIMEUI_LICENSE ? PRIMEUI_LICENSE : undefined;

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes, withComponentInputBinding()),
    provideHttpClient(withInterceptors([apiInterceptor])),
    provideTransloco({
      config: {
        availableLangs: ['ar', 'en'],
        defaultLang: 'ar',
        fallbackLang: 'ar',
        reRenderOnLangChange: true,
        prodMode: !isDevMode(),
        missingHandler: { useFallbackTranslation: true },
      },
      loader: TranslocoHttpLoader,
    }),
    providePrimeNG({
      theme: { preset: SayyaraPreset, options: { darkModeSelector: false, cssLayer: false } },
      license: primeuiLicense,
    }),
    MessageService,
    // Apply the stored language (and <html dir>) before the first render.
    provideAppInitializer(() => {
      inject(LanguageService);
    }),
  ],
};
