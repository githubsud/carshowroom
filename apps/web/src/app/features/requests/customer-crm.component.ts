import { Component, effect, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { TagModule } from 'primeng/tag';

import { CustomerRequest, FollowUp } from '../../core/api/api.models';
import { AppDatePipe, MoneyPipe } from '../../core/format/format.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { CrmService } from './crm.service';
import { LogCallComponent } from './log-call.component';
import { RequestFormDialogComponent } from './request-form-dialog.component';

/** On the customer page: what they asked for, every call, and a one-tap call log. */
@Component({
  selector: 'app-customer-crm',
  imports: [RouterLink, TranslocoPipe, ButtonModule, TagModule, AppDatePipe, MoneyPipe, CanDirective, LogCallComponent,
            RequestFormDialogComponent],
  template: `
    <section class="card" data-testid="customer-crm">
      <div class="head">
        <h2>{{ 'followUps.title' | transloco }}</h2>
        <div class="actions">
          <app-log-call *appCan="'followup.manage'" [customerId]="customerId()" [phone]="phone()" testKey="customer"
                        (logged)="logged()" />
          <p-button *appCan="'request.manage'" icon="pi pi-plus" size="small" [text]="true"
                    [label]="'requests.add' | transloco" (onClick)="formOpen.set(true)" data-testid="customer-add-request" />
        </div>
      </div>
      @if (requests().length) {
        <ul class="list" data-testid="customer-requests">
          @for (r of requests(); track r.id) {
            <li>
              <i class="pi pi-search" aria-hidden="true"></i>
              {{ [r.make, r.model].join(' ') }}
              @if (r.year_from || r.year_to) { {{ r.year_from }}–{{ r.year_to }} }
              @if (r.budget_max) { · ≤ {{ r.budget_max | money }} }
              <p-tag [value]="'requests.status_' + r.status | transloco" severity="secondary" />
              @if (r.match_count) {
                <a [routerLink]="['/t', context.activeTenantId(), 'requests']" class="matches">
                  {{ 'requests.matchCount' | transloco: { n: r.match_count } }}</a>
              }
            </li>
          }
        </ul>
      }
      <ul class="list timeline" data-testid="customer-follow-ups">
        @for (f of followUps(); track f.id) {
          <li>
            <span class="sub">{{ f.occurred_at | appDate }}</span>
            {{ 'followUps.kind_' + f.kind | transloco }}
            @if (f.result) { — <strong>{{ 'followUps.result_' + f.result | transloco }}</strong> }
            @if (f.notes) { — {{ f.notes }} }
            @if (f.next_follow_up_date) { <span class="sub">· {{ 'followUps.next' | transloco }} {{ f.next_follow_up_date | appDate }}</span> }
            @if (f.created_by_name) { <span class="sub">· {{ f.created_by_name }}</span> }
          </li>
        } @empty {
          <li class="sub">{{ 'followUps.none' | transloco }}</li>
        }
      </ul>
    </section>
    <app-request-form-dialog [(visible)]="formOpen" [customerId]="customerId()" (saved)="load()" />
  `,
  styles: `
    .head {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      align-items: center;
      justify-content: space-between;

      h2 {
        margin: 0;
      }
    }
    .actions {
      display: flex;
      gap: var(--space-2);
      align-items: flex-start;
    }
    .list {
      padding: 0;
      margin: var(--space-2) 0 0;
      list-style: none;

      li {
        display: flex;
        flex-wrap: wrap;
        gap: var(--space-1) var(--space-2);
        align-items: center;
        padding-block: var(--space-1);
        border-block-end: 1px solid var(--color-border);
      }
    }
  `,
})
export class CustomerCrmComponent {
  private readonly api = inject(CrmService);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  protected readonly context = inject(TenantContextService);

  readonly customerId = input.required<string>();
  readonly phone = input<string | null>(null);

  protected readonly requests = signal<CustomerRequest[]>([]);
  protected readonly followUps = signal<FollowUp[]>([]);
  protected readonly formOpen = signal(false);

  constructor() {
    effect(() => {
      this.customerId();
      void this.load();
    });
  }

  protected async load(): Promise<void> {
    const [requests, followUps] = await Promise.all([
      this.api.requests({ customer_id: this.customerId(), open_only: false }),
      this.api.followUps(this.customerId(), 20),
    ]);
    this.requests.set(requests);
    this.followUps.set(followUps);
  }

  protected async logged(): Promise<void> {
    this.toast.add({ severity: 'success', summary: this.transloco.translate('followUps.logged') });
    await this.load();
  }
}
