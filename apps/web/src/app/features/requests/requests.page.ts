import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';

import { CustomerRequest, FollowUpDue, RequestMatch, RequestStatus } from '../../core/api/api.models';
import { AppDatePipe, MoneyPipe } from '../../core/format/format.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { loaded, translationsLoaded } from '../../shared/translated';
import { CrmService } from './crm.service';
import { LogCallComponent } from './log-call.component';
import { RequestFormDialogComponent } from './request-form-dialog.component';

export const REQUEST_STATUSES: RequestStatus[] = [
  'NEW',
  'CONTACTED',
  'VEHICLE_FOUND',
  'NEGOTIATING',
  'DEPOSIT',
  'WON',
  'LOST',
  'ON_HOLD',
];

/** “Who wants what” (SPEC §4.6): follow-ups due today, then open requests with their matches. */
@Component({
  selector: 'app-requests-page',
  imports: [
    FormsModule,
    RouterLink,
    TranslocoPipe,
    ButtonModule,
    CheckboxModule,
    InputTextModule,
    SelectModule,
    TableModule,
    TagModule,
    MoneyPipe,
    AppDatePipe,
    CanDirective,
    StateComponent,
    LogCallComponent,
    RequestFormDialogComponent,
  ],
  template: `
    <div class="page-header">
      <h1 class="page-title">{{ 'requests.title' | transloco }}</h1>
      <p-button *appCan="'request.manage'" icon="pi pi-plus" [label]="'requests.add' | transloco"
                (onClick)="formOpen.set(true)" data-testid="add-request" />
    </div>

    <section class="card" data-testid="due-follow-ups">
      <h2>{{ 'followUps.due' | transloco }}
        <span class="check"><p-checkbox [(ngModel)]="mine" (ngModelChange)="loadDue()" [binary]="true" inputId="due-mine" />
          <label for="due-mine">{{ 'followUps.mine' | transloco }}</label></span>
      </h2>
      <ul class="due">
        @for (d of due(); track d.follow_up.id) {
          <li [attr.data-testid]="'due-' + d.follow_up.customer_id">
            <div>
              <a [routerLink]="['/t', context.activeTenantId(), 'customers', d.follow_up.customer_id]">
                <strong>{{ d.follow_up.customer_name }}</strong></a>
              <span dir="ltr" class="sub"> {{ d.follow_up.customer_phone }}</span>
              @if (d.follow_up.priority === 'HIGH') { <p-tag severity="danger" [value]="'followUps.priority_HIGH' | transloco" /> }
              <div class="sub">
                {{ d.follow_up.next_follow_up_date | appDate }}
                @if (d.overdue_days > 0) { <span class="negative">({{ 'installments.daysLate' | transloco: { n: d.overdue_days } }})</span> }
                @if (d.follow_up.notes) { — {{ d.follow_up.notes }} }
                @if (d.follow_up.assigned_name) { · {{ d.follow_up.assigned_name }} }
              </div>
            </div>
            <app-log-call *appCan="'followup.manage'" [customerId]="d.follow_up.customer_id"
                          [requestId]="d.follow_up.request_id" [phone]="d.follow_up.customer_phone"
                          [testKey]="d.follow_up.customer_id" (logged)="logged()" />
          </li>
        } @empty {
          <li class="sub">{{ 'followUps.noneDue' | transloco }}</li>
        }
      </ul>
    </section>

    <div class="filters">
      <input pInputText [(ngModel)]="q" (keyup.enter)="load()" [placeholder]="'customers.searchHint' | transloco"
             [attr.aria-label]="'customers.searchHint' | transloco" />
      <p-select [options]="statusOptions()" [(ngModel)]="status" (ngModelChange)="load()" optionLabel="label"
                optionValue="value" [showClear]="true" [placeholder]="'requests.openOnly' | transloco" />
    </div>
    @if (loadError()) {
      <app-state kind="error" [message]="loadError()" (retry)="load()" />
    } @else {
      <p-table [value]="requests()" styleClass="p-datatable-sm" data-testid="requests" dataKey="id">
        <ng-template #header>
          <tr>
            <th>{{ 'sales.customer' | transloco }}</th>
            <th>{{ 'requests.wants' | transloco }}</th>
            <th>{{ 'vehicles.status' | transloco }}</th>
            <th>{{ 'requests.matches' | transloco }}</th>
            <th></th>
          </tr>
        </ng-template>
        <ng-template #body let-r>
          <tr [attr.data-testid]="'request-' + r.id">
            <td><a [routerLink]="['/t', context.activeTenantId(), 'customers', r.customer_id]">{{ r.customer_name }}</a>
              <div class="sub" dir="ltr">{{ r.customer_phone }}</div></td>
            <td>{{ wants(r) }}
              @if (r.budget_max) { <div class="sub">≤ {{ r.budget_max | money }}</div> }</td>
            <td>
              @if (context.can('request.manage')) {
                <p-select [options]="statusOptions()" [ngModel]="r.status" (ngModelChange)="setStatus(r, $event)"
                          optionLabel="label" optionValue="value" size="small" [attr.aria-label]="'vehicles.status' | transloco" />
              } @else {
                <p-tag [value]="'requests.status_' + r.status | transloco" />
              }
            </td>
            <td>
              @if (r.match_count > 0) {
                <p-button [text]="true" size="small" [label]="'requests.matchCount' | transloco: { n: r.match_count }"
                          (onClick)="toggle(r)" [attr.data-testid]="'matches-' + r.id" />
              } @else { <span class="sub">—</span> }
            </td>
            <td><app-log-call *appCan="'followup.manage'" [customerId]="r.customer_id" [requestId]="r.id"
                              [phone]="r.customer_phone" [compact]="true" [testKey]="r.id" (logged)="logged()" /></td>
          </tr>
          @if (expanded() === r.id) {
            <tr>
              <td colspan="5">
                <ul class="matches">
                  @for (m of matches(); track m.id) {
                    <li>
                      <a [routerLink]="['/t', context.activeTenantId(), 'vehicles', m.vehicle_id]">{{ m.vehicle_label }}
                        ({{ m.stock_no }})</a>
                      @if (m.asking_price) { — {{ m.asking_price | money }} }
                      <p-tag [value]="'vehicles.status_' + m.vehicle_status | transloco" severity="secondary" />
                      @if (m.contacted) { <p-tag severity="success" [value]="'requests.contacted' | transloco" /> }
                    </li>
                  }
                </ul>
              </td>
            </tr>
          }
        </ng-template>
        <ng-template #emptymessage>
          <tr><td colspan="5"><app-state kind="empty" [message]="'requests.none' | transloco" /></td></tr>
        </ng-template>
      </p-table>
    }
    <app-request-form-dialog [(visible)]="formOpen" (saved)="created($event)" />
  `,
  styles: `
    h2 {
      display: flex;
      gap: var(--space-3);
      align-items: center;
      justify-content: space-between;
    }
    .check {
      display: flex;
      gap: var(--space-2);
      align-items: center;
      font-size: 0.875rem;
      font-weight: 400;
    }
    .due,
    .matches {
      padding: 0;
      margin: 0;
      list-style: none;

      li {
        display: flex;
        flex-wrap: wrap;
        gap: var(--space-2);
        align-items: center;
        justify-content: space-between;
        padding-block: var(--space-2);
        border-block-end: 1px solid var(--color-border);
      }
    }
  `,
})
export class RequestsPage implements OnInit {
  private readonly api = inject(CrmService);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  private readonly translations = translationsLoaded();
  protected readonly context = inject(TenantContextService);

  protected readonly requests = signal<CustomerRequest[]>([]);
  protected readonly due = signal<FollowUpDue[]>([]);
  protected readonly matches = signal<RequestMatch[]>([]);
  protected readonly expanded = signal<string | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly formOpen = signal(false);
  protected status: RequestStatus | null = null;
  protected q = '';
  protected mine = false;

  protected readonly statusOptions = computed(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    return REQUEST_STATUSES.map((value) => ({ value, label: this.transloco.translate(`requests.status_${value}`) }));
  });

  ngOnInit(): void {
    void this.load();
    void this.loadDue();
  }

  protected async load(): Promise<void> {
    try {
      this.requests.set(await this.api.requests({ status: this.status, open_only: this.status === null, q: this.q }));
      this.loadError.set(null);
    } catch (error) {
      this.loadError.set(this.errors.message(error));
    }
  }

  protected async loadDue(): Promise<void> {
    try {
      this.due.set(await this.api.dueFollowUps(this.mine));
    } catch {
      this.due.set([]);
    }
  }

  protected wants(r: CustomerRequest): string {
    const years = r.year_from || r.year_to ? `${r.year_from ?? ''}–${r.year_to ?? ''}` : '';
    return [r.make, r.model, years].filter(Boolean).join(' ');
  }

  protected async toggle(r: CustomerRequest): Promise<void> {
    if (this.expanded() === r.id) {
      this.expanded.set(null);
      return;
    }
    this.matches.set((await this.api.request(r.id)).matches ?? []);
    this.expanded.set(r.id);
  }

  protected async setStatus(r: CustomerRequest, status: RequestStatus): Promise<void> {
    try {
      await this.api.updateRequest(r.id, { status });
      await this.load();
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    }
  }

  protected async created(request: CustomerRequest): Promise<void> {
    this.toast.add({
      severity: 'success',
      summary: this.transloco.translate('requests.saved', { n: request.match_count }),
    });
    await this.load();
  }

  protected async logged(): Promise<void> {
    this.toast.add({ severity: 'success', summary: this.transloco.translate('followUps.logged') });
    await Promise.all([this.load(), this.loadDue()]);
  }
}
