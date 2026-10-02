import { inject, Injectable } from '@angular/core';
import { TranslocoService } from '@jsverse/transloco';

import { ApiError } from '../core/api/api.models';

/** Turns an error code from the API or Supabase Auth into a translated sentence. */
@Injectable({ providedIn: 'root' })
export class ErrorMessageService {
  private readonly transloco = inject(TranslocoService);

  message(error: unknown): string {
    const key = `errors.${this.code(error)}`;
    const text = this.transloco.translate(key);
    return text === key ? this.transloco.translate('errors.UNKNOWN_ERROR') : text;
  }

  private code(error: unknown): string {
    if (error instanceof ApiError) {
      return error.code;
    }
    // Supabase Auth errors carry a machine-readable `code` (e.g. invalid_credentials).
    const authCode = (error as { code?: unknown } | null)?.code;
    return typeof authCode === 'string' ? `auth_${authCode}` : 'UNKNOWN_ERROR';
  }
}
