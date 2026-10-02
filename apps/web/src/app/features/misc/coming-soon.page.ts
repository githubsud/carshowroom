import { Component, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { map } from 'rxjs';

/** Placeholder for modules planned in later phases (docs/BACKLOG.md). */
@Component({
  selector: 'app-coming-soon-page',
  imports: [TranslocoPipe],
  template: `
    <h1 class="page-title">{{ 'menu.' + feature() | transloco }}</h1>
    <p class="muted" data-testid="coming-soon">{{ 'common.comingSoon' | transloco }}</p>
  `,
  styles: `
    .muted {
      color: var(--color-text-muted);
    }
  `,
})
export class ComingSoonPage {
  protected readonly feature = toSignal(inject(ActivatedRoute).paramMap.pipe(map((p) => p.get('feature') ?? '')), {
    initialValue: '',
  });
}
