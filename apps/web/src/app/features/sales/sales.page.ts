import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableLazyLoadEvent, TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';

import { SaleListRow, SalePage as SalePageData } from '../../core/api/api.models';
import { AppDatePipe, MoneyPipe } from '../../core/format/format.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { loaded, translationsLoaded } from '../../shared/translated';
import { saleSeverity } from './sale-status';
import { SalesService } from './sales.service';

const PAGE_SIZE = 25;

/** Sales list (SPEC §4.7): drafts, posted and cancelled sales. */
@Component({
  selector: 'app-sales-page',
  imports: [
    FormsModule,
    TranslocoPipe,
    ButtonModule,
    InputTextModule,
    SelectButtonModule,
    TableModule,
    TagModule,
    MoneyPipe,
    AppDatePipe,
    CanDirective,
    StateComponent,
  ],
  template: `
    <div class="page-header">
      <h1 class="page-title">{{ 'sales.title' | transloco }}</h1>
      <p-button *appCan="'sale.draft'" icon="pi pi-plus" data-testid="new-sale" [label]="'sales.new' | transloco"
                (onClick)="newSale()" />
    </div>
    <div class="filters">
      <p-selectbutton [options]="statusOptions()" [(ngModel)]="status" (ngModelChange)="filter()" optionLabel="label"
                      optionValue="value" [allowEmpty]="false" data-testid="sale-status-filter" />
      <input pInputText type="search" [(ngModel)]="q" (keyup.enter)="filter()" (search)="filter()"
             [placeholder]="'sales.searchHint' | transloco" />
    </div>
    @if (loadError()) {
      <app-state kind="error" [message]="loadError()" (retry)="load()" />
    } @else {
      <p-table [value]="page()?.items ?? []" [lazy]="true" (onLazyLoad)="lazy($event)" [paginator]="true"
               [rows]="pageSize" [totalRecords]="page()?.total ?? 0" [loading]="loading()" styleClass="p-datatable-sm"
               data-testid="sales">
        <ng-template #header>
          <tr>
            <th>{{ 'sales.number' | transloco }}</th>
            <th>{{ 'vehicles.vehicle' | transloco }}</th>
            <th>{{ 'sales.buyer' | transloco }}</th>
            <th>{{ 'finance.date' | transloco }}</th>
            <th class="num">{{ 'sales.price' | transloco }}</th>
            <th></th>
          </tr>
        </ng-template>
        <ng-template #body let-s>
          <tr class="clickable" (click)="open(s)" [attr.data-testid]="'sale-row-' + s.sale_no">
            <td dir="ltr">{{ s.invoice_no ?? s.sale_no }}</td>
            <td>{{ s.vehicle_label }}<div class="sub" dir="ltr">{{ s.stock_no }}</div></td>
            <td>{{ s.buyer_name }}</td>
            <td>{{ s.sale_date | appDate }}</td>
            <td class="num">{{ s.sale_price | money }}</td>
            <td><p-tag [severity]="severity(s.status)" [value]="'sales.status_' + s.status | transloco" /></td>
          </tr>
        </ng-template>
        <ng-template #emptymessage>
          <tr><td colspan="6"><app-state kind="empty" [message]="'sales.none' | transloco" /></td></tr>
        </ng-template>
      </p-table>
    }
  `,
  styleUrl: '../vehicles/inventory.page.scss',
})
export class SalesPage implements OnInit {
  private readonly api = inject(SalesService);
  private readonly router = inject(Router);
  private readonly context = inject(TenantContextService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  private readonly translations = translationsLoaded();

  protected readonly page = signal<SalePageData | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly pageSize = PAGE_SIZE;
  protected readonly severity = saleSeverity;
  protected status = '';
  protected q = '';
  private pageNo = 1;

  protected readonly statusOptions = computed(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    return [
      { value: '', label: this.transloco.translate('sales.all') },
      ...(['DRAFT', 'POSTED', 'CANCELLED'] as const).map((value) => ({
        value,
        label: this.transloco.translate(`sales.status_${value}`),
      })),
    ];
  });

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    try {
      this.page.set(
        await this.api.list({ status: this.status || null, q: this.q.trim(), page: this.pageNo, page_size: PAGE_SIZE }),
      );
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

  protected open(row: SaleListRow): void {
    void this.router.navigate(['/t', this.context.activeTenantId(), 'sales', row.id]);
  }

  protected newSale(): void {
    void this.router.navigate(['/t', this.context.activeTenantId(), 'sales', 'new']);
  }
}
