import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';

import { Consignment, ConsignmentOutRow, ExternalShowroom } from '../../core/api/api.models';
import { AppDatePipe, MoneyPipe } from '../../core/format/format.service';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { loaded, translationsLoaded } from '../../shared/translated';
import { ConsignmentFormDialogComponent } from './consignment-form-dialog.component';
import { ConsignmentService } from './consignment.service';

type Tab = 'in' | 'out' | 'showrooms';

/** Consignments (SPEC §4.4, §4.5): cars we hold for owners, our cars at other showrooms, and those showrooms. */
@Component({
  selector: 'app-consignments-page',
  imports: [
    FormsModule,
    RouterLink,
    TranslocoPipe,
    ButtonModule,
    DialogModule,
    InputTextModule,
    SelectButtonModule,
    TableModule,
    TagModule,
    MoneyPipe,
    AppDatePipe,
    StateComponent,
    ConsignmentFormDialogComponent,
  ],
  template: `
    <div class="page-header">
      <h1 class="page-title">{{ 'menu.consignments' | transloco }}</h1>
      <div class="header-actions">
        @if (tab === 'showrooms') {
          <p-button icon="pi pi-plus" [label]="'consignment.addShowroom' | transloco" (onClick)="openShowroom()"
                    data-testid="add-showroom" />
        } @else {
          <p-button icon="pi pi-plus" [label]="'consignment.receive' | transloco" (onClick)="formOpen.set(true)"
                    data-testid="receive-consignment" />
        }
      </div>
    </div>
    <p-selectbutton [options]="tabOptions()" [(ngModel)]="tab" (ngModelChange)="load()" optionLabel="label"
                    optionValue="value" [allowEmpty]="false" data-testid="consignment-tabs" />

    @if (loadError()) {
      <app-state kind="error" [message]="loadError()" (retry)="load()" />
    } @else if (tab === 'in') {
      <p-table [value]="consignments()" styleClass="p-datatable-sm" data-testid="consignments-in">
        <ng-template #header>
          <tr>
            <th>{{ 'vehicles.vehicle' | transloco }}</th>
            <th>{{ 'consignment.owner' | transloco }}</th>
            <th>{{ 'consignment.terms' | transloco }}</th>
            <th>{{ 'consignment.daysWithUs' | transloco }}</th>
            <th>{{ 'vehicles.status' | transloco }}</th>
            @if (canSettle) { <th class="num">{{ 'consignment.dueToOwner' | transloco }}</th> }
          </tr>
        </ng-template>
        <ng-template #body let-c>
          <tr [attr.data-testid]="'consignment-' + c.stock_no">
            <td><a [routerLink]="['/t', context.activeTenantId(), 'consignments', c.id]">{{ c.vehicle_label }}</a>
              <div class="sub" dir="ltr">{{ c.stock_no }}</div></td>
            <td>{{ c.consignor_name }}<div class="sub" dir="ltr">{{ c.consignor_phone }}</div></td>
            <td>{{ terms(c) }}</td>
            <td>{{ c.days_with_us }}
              @if (c.expired) { <p-tag severity="warn" [value]="'consignment.expired' | transloco" /> }</td>
            <td><p-tag [value]="'consignment.status_' + c.status | transloco"
                       [severity]="c.status === 'ACTIVE' ? 'info' : 'secondary'" /></td>
            @if (canSettle) { <td class="num">{{ c.payable | money }}</td> }
          </tr>
        </ng-template>
        <ng-template #emptymessage>
          <tr><td colspan="6"><app-state kind="empty" [message]="'consignment.noneIn' | transloco" /></td></tr>
        </ng-template>
      </p-table>
    } @else if (tab === 'out') {
      <p-table [value]="out()" styleClass="p-datatable-sm" data-testid="consignments-out">
        <ng-template #header>
          <tr>
            <th>{{ 'vehicles.vehicle' | transloco }}</th>
            <th>{{ 'consignment.showroom' | transloco }}</th>
            <th>{{ 'consignment.sentOn' | transloco }}</th>
            <th>{{ 'consignment.daysOut' | transloco }}</th>
            <th>{{ 'vehicles.status' | transloco }}</th>
          </tr>
        </ng-template>
        <ng-template #body let-o>
          <tr [attr.data-testid]="'out-' + o.stock_no">
            <td><a [routerLink]="['/t', context.activeTenantId(), 'vehicles', o.vehicle_id]">{{ o.vehicle_label }}</a>
              <div class="sub" dir="ltr">{{ o.stock_no }}</div></td>
            <td><a [routerLink]="['/t', context.activeTenantId(), 'consignments', 'showrooms', o.external_showroom_id]">
              {{ o.external_showroom_name }}</a></td>
            <td>{{ o.sent_date | appDate }}</td>
            <td [class.negative]="o.status === 'OUT' && (o.days_out ?? 0) > 30">{{ o.days_out }}</td>
            <td><p-tag [value]="'consignment.outStatus_' + o.status | transloco"
                       [severity]="o.status === 'OUT' ? 'info' : 'secondary'" /></td>
          </tr>
        </ng-template>
        <ng-template #emptymessage>
          <tr><td colspan="5"><app-state kind="empty" [message]="'consignment.noneOut' | transloco" /></td></tr>
        </ng-template>
      </p-table>
    } @else {
      <p-table [value]="showrooms()" styleClass="p-datatable-sm" data-testid="showrooms">
        <ng-template #header>
          <tr>
            <th>{{ 'consignment.showroom' | transloco }}</th>
            <th>{{ 'customers.phone' | transloco }}</th>
            <th>{{ 'consignment.carsOut' | transloco }}</th>
            @if (canSettle) { <th class="num">{{ 'consignment.dueToUs' | transloco }}</th> }
          </tr>
        </ng-template>
        <ng-template #body let-s>
          <tr>
            <td><a [routerLink]="['/t', context.activeTenantId(), 'consignments', 'showrooms', s.id]">{{ s.name }}</a>
              @if (s.contact_name) { <div class="sub">{{ s.contact_name }}</div> }</td>
            <td dir="ltr">{{ s.phone }}</td>
            <td>{{ s.cars_out }}</td>
            @if (canSettle) { <td class="num">{{ s.receivable | money }}</td> }
          </tr>
        </ng-template>
        <ng-template #emptymessage>
          <tr><td colspan="4"><app-state kind="empty" [message]="'consignment.noShowrooms' | transloco" /></td></tr>
        </ng-template>
      </p-table>
    }

    <app-consignment-form-dialog [(visible)]="formOpen" (saved)="received($event)" />
    <p-dialog [(visible)]="showroomOpen" [modal]="true" [header]="'consignment.addShowroom' | transloco"
              [style]="{ width: 'min(420px, 96vw)' }">
      <div class="dialog-fields">
        <div class="field"><label for="sr-name">{{ 'customers.name' | transloco }}</label>
          <input pInputText id="sr-name" [(ngModel)]="showroom.name" data-testid="sr-name" /></div>
        <div class="field"><label for="sr-contact">{{ 'consignment.contact' | transloco }}</label>
          <input pInputText id="sr-contact" [(ngModel)]="showroom.contact" /></div>
        <div class="field"><label for="sr-phone">{{ 'customers.phone' | transloco }}</label>
          <input pInputText id="sr-phone" [(ngModel)]="showroom.phone" dir="ltr" inputmode="tel" /></div>
        <p-button [label]="'settings.save' | transloco" (onClick)="saveShowroom()" [disabled]="!showroom.name.trim()"
                  data-testid="sr-save" />
      </div>
    </p-dialog>
  `,
  styles: `
    p-selectbutton {
      display: block;
      margin-block-end: var(--space-3);
    }
  `,
})
export class ConsignmentsPage implements OnInit {
  private readonly api = inject(ConsignmentService);
  private readonly router = inject(Router);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  private readonly translations = translationsLoaded();
  protected readonly context = inject(TenantContextService);

  protected readonly consignments = signal<Consignment[]>([]);
  protected readonly out = signal<ConsignmentOutRow[]>([]);
  protected readonly showrooms = signal<ExternalShowroom[]>([]);
  protected readonly loadError = signal<string | null>(null);
  protected readonly formOpen = signal(false);
  protected readonly showroomOpen = signal(false);
  protected readonly canSettle = this.context.can('consignment.settle');
  protected tab: Tab = 'in';
  protected showroom = { name: '', contact: '', phone: '' };

  protected readonly tabOptions = computed(() =>
    loaded(this.translations())
      ? (['in', 'out', 'showrooms'] as Tab[]).map((value) => ({ value, label: this.transloco.translate(`consignment.tab_${value}`) }))
      : [],
  );

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    try {
      if (this.tab === 'in') {
        this.consignments.set(await this.api.list());
      } else if (this.tab === 'out') {
        this.out.set(await this.api.listOut());
      } else {
        this.showrooms.set(await this.api.showrooms());
      }
      this.loadError.set(null);
    } catch (error) {
      this.loadError.set(this.errors.message(error));
    }
  }

  protected terms(c: Consignment): string {
    const value =
      c.terms_type === 'NET_PRICE'
        ? c.net_price_to_owner
        : c.terms_type === 'COMMISSION_PCT'
          ? `${Number(c.commission_value)}%`
          : c.commission_value;
    return `${this.transloco.translate(`consignment.terms_${c.terms_type}`)}: ${value ?? ''}`;
  }

  protected received(consignment: Consignment): void {
    this.toast.add({ severity: 'success', summary: this.transloco.translate('consignment.received') });
    void this.router.navigate(['/t', this.context.activeTenantId(), 'consignments', consignment.id]);
  }

  protected openShowroom(): void {
    this.showroom = { name: '', contact: '', phone: '' };
    this.showroomOpen.set(true);
  }

  protected async saveShowroom(): Promise<void> {
    try {
      await this.api.createShowroom({
        name: this.showroom.name.trim(),
        contact_name: this.showroom.contact.trim() || null,
        phone: this.showroom.phone.trim() || null,
      });
      this.showroomOpen.set(false);
      await this.load();
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    }
  }
}
