import { Component, input, output } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { SkeletonModule } from 'primeng/skeleton';

/** Explicit loading, empty and error states (SPEC §9.3 design system). */
@Component({
  selector: 'app-state',
  imports: [TranslocoPipe, ButtonModule, SkeletonModule],
  template: `
    @switch (kind()) {
      @case ('loading') {
        <div class="state" role="status" [attr.aria-label]="'common.loading' | transloco">
          <p-skeleton width="60%" height="1.25rem" />
          <p-skeleton width="90%" height="1rem" />
          <p-skeleton width="75%" height="1rem" />
        </div>
      }
      @case ('empty') {
        <div class="state centered">
          <i class="pi pi-inbox" aria-hidden="true"></i>
          <p>{{ message() ?? ('common.empty' | transloco) }}</p>
        </div>
      }
      @case ('error') {
        <div class="state centered error" role="alert">
          <i class="pi pi-exclamation-triangle" aria-hidden="true"></i>
          <p>{{ message() ?? ('errors.UNKNOWN_ERROR' | transloco) }}</p>
          <p-button type="button" [outlined]="true" [label]="'common.retry' | transloco" (onClick)="retry.emit()" />
        </div>
      }
    }
  `,
  styles: `
    .state {
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
      padding: var(--space-4);
    }

    .centered {
      align-items: center;
      color: var(--color-text-muted);
      text-align: center;
    }

    .centered i {
      font-size: 2rem;
    }

    .error {
      color: var(--color-danger);
    }
  `,
})
export class StateComponent {
  readonly kind = input.required<'loading' | 'empty' | 'error'>();
  readonly message = input<string | null>(null);
  readonly retry = output<void>();
}
