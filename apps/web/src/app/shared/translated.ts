import { inject, Signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { Translation, TranslocoService } from '@jsverse/transloco';

/**
 * A signal that changes whenever the active translation is loaded or switched.
 * Read it inside a computed() that calls transloco.translate(), so labels built
 * in code never get stuck on raw keys while the translation file is loading.
 */
export function translationsLoaded(): Signal<Translation> {
  return toSignal(inject(TranslocoService).selectTranslation(), { initialValue: {} });
}
