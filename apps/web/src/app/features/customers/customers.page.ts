import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TableLazyLoadEvent, TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';

import { Customer, CustomerPage as CustomerPageData } from '../../core/api/api.models';
import { CanDirective } from '../../core/permissions/can.directive';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { loaded, translationsLoaded } from '../../shared/translated';
import { CustomerFormDialogComponent } from './customer-form-dialog.component';
import { CustomersService } from './customers.service';

const PAGE_SIZE = 25;

/** Customers (SPEC §4.6): phone-first search, buyers, sellers, consignors. */
@Component({
  selector: 'app-customers-page',
  imports: [
    FormsModule,
    TranslocoPipe,
    ButtonModule,
    InputTextModule,
    SelectModule,
    TableModule,
    TagModule,
    CanDirective,
    StateComponent,
    CustomerFormDialogComponent,
  ],
  template: `
    <div class="page-header">
      <h1 class="page-title">{{ 'customers.title' | transloco }}</h1>
      <p-button *appCan="'customer.manage'" icon="pi pi-user-plus" data-testid="add-customer"
                [label]="'customers.add' | transloco" (onClick)="addOpen.set(true)" />
    </div>
    <div class="filters">
      <input pInputText type="search" [(ngModel)]="q" (keyup.enter)="filter()" (search)="filter()"
             [placeholder]="'customers.searchHint' | transloco" data-testid="customer-search" />
      <p-select [options]="roleOptions()" [(ngModel)]="role" (ngModelChange)="filter()" optionLabel="label"
                optionValue="value" [showClear]="true" [placeholder]="'customers.allRoles' | transloco" />
    </div>
    @if (loadError()) {
      <app-state kind="error" [message]="loadError()" (retry)="load()" />
    } @else {
      <p-table [value]="page()?.items ?? []" [lazy]="true" (onLazyLoad)="lazy($event)" [paginator]="true"
               [rows]="pageSize" [totalRecords]="page()?.total ?? 0" [loading]="loading()" styleClass="p-datatable-sm"
               data-testid="customers">
        <ng-template #header>
          <tr>
            <th>{{ 'customers.name' | transloco }}</th>
            <th>{{ 'customers.phone' | transloco }}</th>
            <th></th>
          </tr>
        </ng-template>
        <ng-template #body let-c>
          <tr class="clickable" (click)="open(c)" [attr.data-testid]="'customer-row-' + c.id">
            <td class="name">{{ c.name }}</td>
            <td dir="ltr" class="phone">{{ c.phone_primary }}</td>
            <td class="tags">
              @if (c.is_buyer) { <p-tag severity="info" [value]="'customers.buyer' | transloco" /> }
              @if (c.is_seller) { <p-tag severity="secondary" [value]="'customers.seller' | transloco" /> }
              @if (c.is_consignor) { <p-tag severity="warn" [value]="'customers.consignor' | transloco" /> }
            </td>
          </tr>
        </ng-template>
        <ng-template #emptymessage>
          <tr><td colspan="3"><app-state kind="empty" [message]="'customers.none' | transloco" /></td></tr>
        </ng-template>
      </p-table>
    }
    <app-customer-form-dialog [(visible)]="addOpen" [initialName]="q" (saved)="open($event)" />
  `,
  styleUrl: '../vehicles/inventory.page.scss',
})
export class CustomersPage implements OnInit {
  private readonly api = inject(CustomersService);
  private readonly router = inject(Router);
  private readonly context = inject(TenantContextService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  private readonly translations = translationsLoaded();

  protected readonly page = signal<CustomerPageData | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly addOpen = signal(false);
  protected readonly pageSize = PAGE_SIZE;
  protected q = '';
  protected role: string | null = null;
  private pageNo = 1;

  protected readonly roleOptions = computed(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    return (['BUYER', 'SELLER', 'CONSIGNOR'] as const).map((value) => ({
      value,
      label: this.transloco.translate(`customers.role_${value}`),
    }));
  });

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    try {
      this.page.set(await this.api.list({ q: this.q.trim(), role: this.role, page: this.pageNo, page_size: PAGE_SIZE }));
      this.loadError.set(null);
    } catch (error) {
      this.loadError.set(this.errors.message(error));
    } finally {
      this.loading.set(false);
    }
  }

  protected filter(): void {
    this.pageNo = 1;
    void this.load();
  }

  protected lazy(event: TableLazyLoadEvent): void {
    const next = Math.floor((event.first ?? 0) / PAGE_SIZE) + 1;
    if (next !== this.pageNo) {
      this.pageNo = next;
      void this.load();
    }
  }

  protected open(customer: Customer): void {
    void this.router.navigate(['/t', this.context.activeTenantId(), 'customers', customer.id]);
  }
}
