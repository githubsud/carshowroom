import { Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

import { InstallmentsService } from '../../features/installments/installments.service';
import { NotificationItem } from '../api/api.models';
import { FormatService } from '../format/format.service';
import { TenantContextService } from '../tenant/tenant-context.service';

const REFRESH_MS = 60_000;

/** In-app notification centre (SPEC §4.17): unread count, list, mark as read. */
@Component({
  selector: 'app-notification-bell',
  imports: [TranslocoPipe],
  template: `
    <div class="bell" (focusout)="blur($event)">
      <button type="button" class="trigger" (click)="toggle()" [attr.aria-label]="'notifications.title' | transloco"
              [attr.aria-expanded]="open()" data-testid="notification-bell">
        <i class="pi pi-bell" aria-hidden="true"></i>
        @if (unread() > 0) { <span class="badge" data-testid="notification-count">{{ unread() }}</span> }
      </button>
      @if (open()) {
        <div class="panel" role="dialog" [attr.aria-label]="'notifications.title' | transloco" data-testid="notifications">
          <div class="head">
            <strong>{{ 'notifications.title' | transloco }}</strong>
            @if (unread() > 0) {
              <button type="button" class="link" (click)="readAll()">{{ 'notifications.readAll' | transloco }}</button>
            }
          </div>
          @for (item of items(); track item.id) {
            <button type="button" class="item" [class.unread]="!item.read" (click)="go(item)">
              <span>{{ 'notifications.kind_' + item.kind | transloco: display(item) }}</span>
              <small>{{ format.date(item.created_at) }}</small>
            </button>
          } @empty {
            <p class="empty">{{ 'notifications.none' | transloco }}</p>
          }
        </div>
      }
    </div>
  `,
  styles: `
    .bell {
      position: relative;
    }
    .trigger {
      position: relative;
      padding: 6px 8px;
      font-size: 1.1rem;
      color: inherit;
      cursor: pointer;
      background: none;
      border: none;
    }
    .badge {
      position: absolute;
      inset-block-start: 0;
      inset-inline-end: 0;
      min-inline-size: 1.1rem;
      padding: 0 4px;
      font-size: 0.6875rem;
      font-weight: 700;
      line-height: 1.1rem;
      color: #fff;
      text-align: center;
      background: var(--color-danger, #dc2626);
      border-radius: 999px;
    }
    .panel {
      position: absolute;
      inset-block-start: calc(100% + 6px);
      inset-inline-end: 0;
      z-index: 1100;
      inline-size: min(22rem, 92vw);
      max-block-size: 70vh;
      overflow-y: auto;
      color: var(--color-text, #0f172a);
      background: var(--color-surface, #fff);
      border: 1px solid var(--color-border);
      border-radius: 6px;
      box-shadow: 0 8px 24px rgb(15 23 42 / 12%);
    }
    .head {
      display: flex;
      justify-content: space-between;
      padding: 8px 12px;
      border-block-end: 1px solid var(--color-border);
    }
    .link {
      padding: 0;
      font: inherit;
      color: var(--color-primary);
      cursor: pointer;
      background: none;
      border: none;
    }
    .item {
      display: flex;
      flex-direction: column;
      gap: 2px;
      inline-size: 100%;
      padding: 8px 12px;
      font: inherit;
      color: inherit;
      text-align: start;
      cursor: pointer;
      background: none;
      border: none;
      border-block-end: 1px solid var(--color-border);
    }
    .item.unread {
      font-weight: 600;
      background: var(--color-background);
    }
    small,
    .empty {
      color: var(--color-text-muted);
    }
    .empty {
      padding: 12px;
      margin: 0;
    }
  `,
})
export class NotificationBellComponent implements OnInit {
  private readonly api = inject(InstallmentsService);
  private readonly router = inject(Router);
  private readonly context = inject(TenantContextService);
  protected readonly format = inject(FormatService);

  protected readonly open = signal(false);
  protected readonly items = signal<NotificationItem[]>([]);
  protected readonly unread = signal(0);

  constructor() {
    const timer = setInterval(() => void this.refresh(), REFRESH_MS);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  ngOnInit(): void {
    void this.refresh();
  }

  async refresh(): Promise<void> {
    try {
      const page = await this.api.notifications();
      this.items.set(page.items);
      this.unread.set(page.unread);
    } catch {
      // Notifications are a convenience; a failed refresh is retried on the next tick.
    }
  }

  /** Amounts and dates in the message, formatted like everywhere else. */
  protected display(item: NotificationItem): Record<string, unknown> {
    const params: Record<string, unknown> = { ...item.params };
    for (const key of ['amount', 'remaining']) {
      if (typeof params[key] === 'string') {
        params[key] = this.format.money(params[key] as string);
      }
    }
    if (typeof params['due_date'] === 'string') {
      params['due_date'] = this.format.date(params['due_date'] as string);
    }
    return params;
  }

  protected toggle(): void {
    this.open.update((value) => !value);
    if (this.open()) {
      void this.refresh();
    }
  }

  protected async readAll(): Promise<void> {
    await this.api.markAllRead();
    await this.refresh();
  }

  protected async go(item: NotificationItem): Promise<void> {
    this.open.set(false);
    if (!item.read) {
      await this.api.markRead(item.id);
      void this.refresh();
    }
    const tenant = this.context.activeTenantId();
    const planId = item.params['plan_id'];
    if (item.entity_type === 'DEFERRED_PAPER') {
      await this.router.navigate(['/t', tenant, 'installments', 'papers']);
    } else if (typeof planId === 'string') {
      await this.router.navigate(['/t', tenant, 'installments', 'plans', planId]);
    } else {
      await this.router.navigate(['/t', tenant, 'installments']);
    }
  }

  protected blur(event: FocusEvent): void {
    const next = event.relatedTarget as Node | null;
    if (!next || !(event.currentTarget as HTMLElement).contains(next)) {
      setTimeout(() => this.open.set(false), 150);
    }
  }
}
