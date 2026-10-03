import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';

import { NotificationItem } from '../../core/api/api.models';
import { FormatService } from '../../core/format/format.service';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { InstallmentsService } from '../installments/installments.service';

/** Notification centre (BACKLOG 7.7): every alert with read/unread and a link to its record. */
@Component({
  selector: 'app-notifications-page',
  imports: [FormsModule, TranslocoPipe, ButtonModule, CheckboxModule, StateComponent],
  template: `
    <div class="page-header">
      <h1 class="page-title">{{ 'notifications.title' | transloco }}</h1>
      <div class="header-actions">
        <span class="check"><p-checkbox [(ngModel)]="unreadOnly" (ngModelChange)="load()" [binary]="true" inputId="n-unread" />
          <label for="n-unread">{{ 'notifications.unreadOnly' | transloco }}</label></span>
        @if (unread() > 0) {
          <p-button [text]="true" [label]="'notifications.readAll' | transloco" (onClick)="readAll()" />
        }
      </div>
    </div>
    <ul class="list" data-testid="notification-list">
      @for (item of items(); track item.id) {
        <li [class.unread]="!item.read">
          <button type="button" (click)="go(item)">
            <span>{{ 'notifications.kind_' + item.kind | transloco: display(item) }}</span>
            <small>{{ format.date(item.created_at) }}</small>
          </button>
        </li>
      } @empty {
        <li><app-state kind="empty" [message]="'notifications.none' | transloco" /></li>
      }
    </ul>
  `,
  styles: `
    .check {
      display: flex;
      gap: var(--space-2);
      align-items: center;
    }
    .list {
      padding: 0;
      margin: 0;
      list-style: none;

      button {
        display: flex;
        gap: var(--space-2);
        justify-content: space-between;
        inline-size: 100%;
        padding: var(--space-2);
        font: inherit;
        color: inherit;
        text-align: start;
        cursor: pointer;
        background: none;
        border: none;
        border-block-end: 1px solid var(--color-border);
      }
      li.unread button {
        font-weight: 600;
        background: #eff6ff;
      }
      small {
        color: var(--color-text-muted);
        white-space: nowrap;
      }
    }
  `,
})
export class NotificationsPage implements OnInit {
  private readonly api = inject(InstallmentsService);
  private readonly router = inject(Router);
  private readonly context = inject(TenantContextService);
  protected readonly format = inject(FormatService);

  protected readonly items = signal<NotificationItem[]>([]);
  protected readonly unread = signal(0);
  protected unreadOnly = false;

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    const page = await this.api.notifications(this.unreadOnly);
    this.items.set(page.items);
    this.unread.set(page.unread);
  }

  protected display(item: NotificationItem): Record<string, unknown> {
    const params: Record<string, unknown> = { ...item.params };
    for (const key of ['amount', 'remaining', 'profit']) {
      if (typeof params[key] === 'string') {
        params[key] = this.format.money(params[key] as string);
      }
    }
    for (const key of ['due_date', 'date']) {
      if (typeof params[key] === 'string') {
        params[key] = this.format.date(params[key] as string);
      }
    }
    return params;
  }

  protected async readAll(): Promise<void> {
    await this.api.markAllRead();
    await this.load();
  }

  protected async go(item: NotificationItem): Promise<void> {
    if (!item.read) {
      await this.api.markRead(item.id);
    }
    const tenant = this.context.activeTenantId();
    const link = item.params['link'];
    const planId = item.params['plan_id'];
    if (typeof link === 'string' && link) {
      await this.router.navigate(['/t', tenant, ...link.split('/')]);
    } else if (item.entity_type === 'VEHICLE' && item.entity_id) {
      await this.router.navigate(['/t', tenant, 'vehicles', item.entity_id]);
    } else if (item.entity_type === 'DEFERRED_PAPER') {
      await this.router.navigate(['/t', tenant, 'installments', 'papers']);
    } else if (typeof planId === 'string') {
      await this.router.navigate(['/t', tenant, 'installments', 'plans', planId]);
    } else {
      await this.load();
    }
  }
}
