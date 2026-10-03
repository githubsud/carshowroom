import { Component, effect, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { TagModule } from 'primeng/tag';

import { RequestMatch } from '../../core/api/api.models';
import { CanDirective } from '../../core/permissions/can.directive';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { ErrorMessageService } from '../../shared/error-message.service';
import { CrmService } from './crm.service';
import { LogCallComponent } from './log-call.component';

/** “N customers asked for this car” with their phones (BACKLOG 6.6). */
@Component({
  selector: 'app-vehicle-matches',
  imports: [RouterLink, TranslocoPipe, ButtonModule, TagModule, CanDirective, LogCallComponent],
  template: `
    @if (matches().length) {
      <section class="card notice-card" data-testid="vehicle-matches">
        <h2><i class="pi pi-users" aria-hidden="true"></i> {{ 'requests.askedFor' | transloco: { n: matches().length } }}</h2>
        <ul>
          @for (m of matches(); track m.id) {
            <li [attr.data-testid]="'match-' + m.request_id">
              <div>
                <a [routerLink]="['/t', context.activeTenantId(), 'customers', m.customer_id]"><strong>{{ m.customer_name }}</strong></a>
                @if (m.customer_phone) { <a class="phone" [href]="'tel:' + m.customer_phone" dir="ltr">{{ m.customer_phone }}</a> }
                <div class="sub" dir="auto">{{ m.request_summary }}</div>
              </div>
              <div class="actions">
                @if (m.contacted) {
                  <p-tag severity="success" [value]="'requests.contacted' | transloco" />
                } @else {
                  <p-button *appCan="'request.manage'" size="small" [outlined]="true" icon="pi pi-check"
                            [label]="'requests.markContacted' | transloco" (onClick)="contacted(m)"
                            [attr.data-testid]="'contacted-' + m.request_id" />
                }
                <app-log-call *appCan="'followup.manage'" [customerId]="m.customer_id" [requestId]="m.request_id"
                              [phone]="m.customer_phone" [compact]="true" [testKey]="m.request_id" />
              </div>
            </li>
          }
        </ul>
      </section>
    }
  `,
  styles: `
    ul {
      padding: 0;
      margin: 0;
      list-style: none;
    }
    li {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      align-items: center;
      justify-content: space-between;
      padding-block: var(--space-2);
      border-block-end: 1px solid var(--color-border);
    }
    .phone {
      margin-inline-start: var(--space-2);
    }
    .actions {
      display: flex;
      gap: var(--space-2);
      align-items: center;
    }
  `,
})
export class VehicleMatchesComponent {
  private readonly api = inject(CrmService);
  private readonly toast = inject(MessageService);
  private readonly errors = inject(ErrorMessageService);
  protected readonly context = inject(TenantContextService);

  readonly vehicleId = input.required<string>();
  /** Reloads when the car's status changes (it may have just become available). */
  readonly status = input<string>('');

  protected readonly matches = signal<RequestMatch[]>([]);

  constructor() {
    effect(() => {
      const id = this.vehicleId();
      this.status();
      if (this.context.can('customer.view')) {
        void this.api.vehicleMatches(id).then(
          (m) => this.matches.set(m),
          () => this.matches.set([]),
        );
      }
    });
  }

  protected async contacted(match: RequestMatch): Promise<void> {
    try {
      const updated = await this.api.setContacted(match.id, true);
      this.matches.update((all) => all.map((m) => (m.id === updated.id ? updated : m)));
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    }
  }
}
