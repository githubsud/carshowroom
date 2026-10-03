import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { TagModule } from 'primeng/tag';

import { AuditRow } from '../../core/api/api.models';
import { FormatService } from '../../core/format/format.service';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { PlatformService } from '../admin/platform.service';

export interface FieldChange {
  field: string;
  before: string;
  after: string;
}

const IGNORED = new Set(['updated_at', 'updated_by', 'created_at', 'created_by']);

/** Fields whose value differs between the row before and after (the JSON diff). */
export function diffRows(before: Record<string, unknown> | null | undefined, after: Record<string, unknown> | null | undefined): FieldChange[] {
  const keys = new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})]);
  const show = (v: unknown) => (v === undefined || v === null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v));
  return [...keys]
    .filter((k) => !IGNORED.has(k) && JSON.stringify(before?.[k]) !== JSON.stringify(after?.[k]))
    .sort()
    .map((field) => ({ field, before: show(before?.[field]), after: show(after?.[field]) }));
}

/** Audit log viewer (SPEC §4.15): who did what, when, with the before/after of every change. */
@Component({
  selector: 'app-audit-page',
  imports: [FormsModule, TranslocoPipe, ButtonModule, InputTextModule, TagModule, StateComponent],
  template: `
    <div class="page-header"><h1 class="page-title">{{ 'audit.title' | transloco }}</h1></div>
    <div class="filters">
      <input pInputText [(ngModel)]="entity" [placeholder]="'audit.entity' | transloco" [attr.aria-label]="'audit.entity' | transloco"
             dir="ltr" data-testid="audit-entity" />
      <input pInputText [(ngModel)]="action" [placeholder]="'audit.action' | transloco" [attr.aria-label]="'audit.action' | transloco"
             dir="ltr" />
      <input pInputText type="date" [(ngModel)]="from" [attr.aria-label]="'reports.from' | transloco" />
      <input pInputText type="date" [(ngModel)]="to" [attr.aria-label]="'reports.to' | transloco" />
      <p-button icon="pi pi-search" [label]="'reports.run' | transloco" (onClick)="load(1)" data-testid="audit-search" />
    </div>
    @if (error()) {
      <app-state kind="error" [message]="error()" (retry)="load(page)" />
    } @else {
      <ul class="events" data-testid="audit-list">
        @for (row of rows(); track row.id) {
          <li>
            <button type="button" class="head" (click)="toggle(row.id)">
              <span class="when">{{ format.date(row.occurred_at) }} {{ row.occurred_at.slice(11, 16) }}</span>
              <p-tag [value]="row.action" [severity]="row.actor_kind === 'PLATFORM' ? 'warn' : 'secondary'" />
              <span dir="ltr">{{ row.entity_type }}</span>
              <span>{{ row.actor_name ?? row.actor_kind }}</span>
            </button>
            @if (open() === row.id) {
              <table class="diff" data-testid="audit-diff">
                <tbody>
                  @for (c of changes(row); track c.field) {
                    <tr><th dir="ltr">{{ c.field }}</th><td class="before">{{ c.before }}</td><td class="after">{{ c.after }}</td></tr>
                  } @empty {
                    <tr><td colspan="3" class="sub" dir="ltr">{{ details(row) }}</td></tr>
                  }
                </tbody>
              </table>
            }
          </li>
        } @empty {
          <li><app-state kind="empty" [message]="'audit.none' | transloco" /></li>
        }
      </ul>
      <div class="pager">
        <p-button [text]="true" icon="pi pi-angle-right" (onClick)="load(page - 1)" [disabled]="page <= 1"
                  [ariaLabel]="'audit.previous' | transloco" />
        <span>{{ page }} / {{ pages() }}</span>
        <p-button [text]="true" icon="pi pi-angle-left" (onClick)="load(page + 1)" [disabled]="page >= pages()"
                  [ariaLabel]="'audit.next' | transloco" />
      </div>
    }
  `,
  styles: `
    .filters {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      margin-block-end: var(--space-3);
    }
    .events {
      padding: 0;
      margin: 0;
      list-style: none;

      li {
        border-block-end: 1px solid var(--color-border);
      }
    }
    .head {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      align-items: center;
      inline-size: 100%;
      padding: var(--space-2);
      font: inherit;
      color: inherit;
      text-align: start;
      cursor: pointer;
      background: none;
      border: none;
    }
    .when {
      color: var(--color-text-muted);
      white-space: nowrap;
    }
    .diff {
      inline-size: 100%;
      margin-block-end: var(--space-2);
      font-size: 0.85rem;
      border-collapse: collapse;

      th,
      td {
        padding: 2px var(--space-2);
        text-align: start;
        overflow-wrap: anywhere;
      }
      .before {
        color: #b91c1c;
        text-decoration: line-through;
      }
      .after {
        color: #166534;
      }
    }
    .pager {
      display: flex;
      gap: var(--space-2);
      align-items: center;
      justify-content: center;
    }
  `,
})
export class AuditPage implements OnInit {
  private readonly api = inject(PlatformService);
  private readonly errors = inject(ErrorMessageService);
  protected readonly format = inject(FormatService);

  protected readonly rows = signal<AuditRow[]>([]);
  protected readonly pages = signal(1);
  protected readonly open = signal<number | null>(null);
  protected readonly error = signal<string | null>(null);
  protected entity = '';
  protected action = '';
  protected from = '';
  protected to = '';
  protected page = 1;

  ngOnInit(): void {
    void this.load(1);
  }

  protected async load(page: number): Promise<void> {
    try {
      const result = await this.api.audit({
        entity_type: this.entity.trim() || null,
        action: this.action.trim() || null,
        date_from: this.from || null,
        date_to: this.to || null,
        page,
        page_size: 50,
      });
      this.page = page;
      this.rows.set(result.items);
      this.pages.set(Math.max(1, Math.ceil(result.total / result.page_size)));
      this.error.set(null);
    } catch (error) {
      this.error.set(this.errors.message(error));
    }
  }

  protected toggle(id: number): void {
    this.open.update((current) => (current === id ? null : id));
  }

  protected changes(row: AuditRow): FieldChange[] {
    return diffRows(row.before as Record<string, unknown> | null, row.after as Record<string, unknown> | null);
  }

  protected details(row: AuditRow): string {
    return row.details ? JSON.stringify(row.details) : '';
  }
}
