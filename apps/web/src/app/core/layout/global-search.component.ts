import { Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

import { VehiclesService } from '../../features/vehicles/vehicles.service';
import { SearchResult } from '../api/api.models';
import { TenantContextService } from '../tenant/tenant-context.service';

/**
 * Quick search, always in the top bar (SPEC §4.3): a car by stock number,
 * plate, make/model or the last digits of its VIN; a customer by name or phone.
 * Results carry no cost data (ARCHITECTURE §5).
 */
@Component({
  selector: 'app-global-search',
  imports: [TranslocoPipe],
  template: `
    <div class="search" (focusout)="blur($event)">
      <i class="pi pi-search" aria-hidden="true"></i>
      <input type="search" [value]="query()" (input)="type($event)" (keydown.escape)="close()"
             (keydown.enter)="first()" [placeholder]="'search.placeholder' | transloco"
             [attr.aria-label]="'search.placeholder' | transloco" data-testid="global-search" />
      @if (open() && result(); as r) {
        <div class="panel" role="listbox" data-testid="search-results">
          @for (v of r.vehicles; track v.id) {
            <button type="button" role="option" [attr.aria-selected]="false" (click)="go('vehicles', v.id)" [attr.data-testid]="'hit-vehicle-' + v.stock_no">
              <i class="pi pi-car" aria-hidden="true"></i>
              <span>{{ v.label }}</span>
              <small dir="ltr">{{ v.stock_no }}{{ v.plate_no ? ' · ' + v.plate_no : '' }}</small>
            </button>
          }
          @for (c of r.customers; track c.id) {
            <button type="button" role="option" [attr.aria-selected]="false" (click)="go('customers', c.id)" [attr.data-testid]="'hit-customer-' + c.id">
              <i class="pi pi-user" aria-hidden="true"></i>
              <span>{{ c.name }}</span>
              <small dir="ltr">{{ c.phone_primary }}</small>
            </button>
          }
          @if (r.vehicles.length === 0 && r.customers.length === 0) {
            <p class="empty">{{ 'search.none' | transloco }}</p>
          }
        </div>
      }
    </div>
  `,
  styles: `
    .search {
      position: relative;
      display: flex;
      align-items: center;
      inline-size: min(22rem, 40vw);
    }
    .pi-search {
      position: absolute;
      inset-inline-start: 10px;
      color: var(--color-text-muted);
    }
    input {
      inline-size: 100%;
      padding: 6px 10px 6px 32px;
      padding-inline: 32px 10px;
      font: inherit;
      border: 1px solid var(--color-border);
      border-radius: 6px;
    }
    .panel {
      position: absolute;
      inset-block-start: calc(100% + 4px);
      inset-inline: 0;
      z-index: 1100;
      max-block-size: 60vh;
      overflow-y: auto;
      background: var(--color-surface, #fff);
      border: 1px solid var(--color-border);
      border-radius: 6px;
      box-shadow: 0 8px 24px rgb(15 23 42 / 12%);
    }
    button {
      display: flex;
      gap: 8px;
      align-items: center;
      inline-size: 100%;
      padding: 8px 12px;
      font: inherit;
      color: inherit;
      text-align: start;
      cursor: pointer;
      background: none;
      border: none;
    }
    button:hover,
    button:focus {
      background: var(--color-background);
    }
    small {
      margin-inline-start: auto;
      color: var(--color-text-muted);
    }
    .empty {
      padding: 8px 12px;
      margin: 0;
      color: var(--color-text-muted);
    }
    @media (width <= 640px) {
      .search {
        inline-size: 9rem;
      }
    }
  `,
})
export class GlobalSearchComponent {
  private readonly api = inject(VehiclesService);
  private readonly router = inject(Router);
  private readonly context = inject(TenantContextService);

  protected readonly query = signal('');
  protected readonly result = signal<SearchResult | null>(null);
  protected readonly open = signal(false);
  private timer: ReturnType<typeof setTimeout> | undefined;
  private seq = 0;

  protected type(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.query.set(value);
    clearTimeout(this.timer);
    if (value.trim().length < 2) {
      this.close();
      return;
    }
    this.timer = setTimeout(() => void this.search(value.trim()), 250);
  }

  private async search(q: string): Promise<void> {
    const seq = ++this.seq;
    try {
      const result = await this.api.search(q);
      if (seq === this.seq) {
        this.result.set(result);
        this.open.set(true);
      }
    } catch {
      this.close();
    }
  }

  protected first(): void {
    const r = this.result();
    if (r?.vehicles[0]) {
      this.go('vehicles', r.vehicles[0].id);
    } else if (r?.customers[0]) {
      this.go('customers', r.customers[0].id);
    }
  }

  protected go(section: 'vehicles' | 'customers', id: string): void {
    this.close();
    this.query.set('');
    void this.router.navigate(['/t', this.context.activeTenantId(), section, id]);
  }

  protected close(): void {
    this.open.set(false);
    this.result.set(null);
  }

  protected blur(event: FocusEvent): void {
    // Keep the panel open while focus moves into it (clicking a result).
    const next = event.relatedTarget as Node | null;
    if (!next || !(event.currentTarget as HTMLElement).contains(next)) {
      setTimeout(() => this.open.set(false), 150);
    }
  }
}
