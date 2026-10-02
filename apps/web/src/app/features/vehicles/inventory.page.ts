import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { SelectButtonModule } from 'primeng/selectbutton';
import { TableLazyLoadEvent, TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';

import { CashAccount, Location, Vehicle, VehiclePage, VehicleRow, VehicleStatus } from '../../core/api/api.models';
import { MoneyPipe } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { loaded, translationsLoaded } from '../../shared/translated';
import { FinanceService } from '../finance/finance.service';
import { PurchaseDialogComponent } from './purchase-dialog.component';
import { statusSeverity } from './vehicle-status';
import { VehicleFormDialogComponent } from './vehicle-form-dialog.component';
import { VehiclesService } from './vehicles.service';

type Scope = 'stock' | 'sold' | 'all';
const SCOPES: Record<Scope, readonly VehicleStatus[]> = {
  stock: ['DRAFT', 'IN_PREPARATION', 'AVAILABLE', 'RESERVED', 'AT_OTHER_SHOWROOM'],
  sold: ['SOLD', 'DELIVERED'],
  all: [],
};
const PAGE_SIZE = 20;

/** Inventory (SPEC §4.3, screen 3): filters, days in stock with aging colours, cost if allowed. */
@Component({
  selector: 'app-inventory-page',
  imports: [
    FormsModule,
    TranslocoPipe,
    ButtonModule,
    InputTextModule,
    SelectModule,
    SelectButtonModule,
    TableModule,
    TagModule,
    MoneyPipe,
    CanDirective,
    StateComponent,
    VehicleFormDialogComponent,
    PurchaseDialogComponent,
  ],
  templateUrl: './inventory.page.html',
  styleUrl: './inventory.page.scss',
})
export class InventoryPage implements OnInit {
  private readonly api = inject(VehiclesService);
  private readonly finance = inject(FinanceService);
  private readonly router = inject(Router);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  private readonly translations = translationsLoaded();
  protected readonly context = inject(TenantContextService);
  protected readonly language = inject(LanguageService);

  protected readonly page = signal<VehiclePage | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly locations = signal<Location[]>([]);
  protected readonly accounts = signal<CashAccount[]>([]);

  protected scope: Scope = 'stock';
  protected q = '';
  protected aging: string | null = null;
  protected sort = 'stock_date';
  private pageNo = 1;

  protected readonly scopeOptions = computed(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    return (['stock', 'sold', 'all'] as const).map((value) => ({
      value,
      label: this.transloco.translate(`vehicles.scope_${value}`),
    }));
  });
  protected readonly agingOptions = computed(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    return (['FRESH', 'AGING', 'OLD', 'STALE'] as const).map((value) => ({
      value,
      label: this.transloco.translate(`vehicles.aging_${value}`),
    }));
  });
  protected readonly sortOptions = computed(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    return ['stock_date', '-created', 'price', '-price', 'make'].map((value) => ({
      value,
      label: this.transloco.translate(`vehicles.sort_${value}`),
    }));
  });

  protected readonly formOpen = signal(false);
  protected readonly purchaseOpen = signal(false);
  protected readonly created = signal<Vehicle | null>(null);
  protected readonly pageSize = PAGE_SIZE;
  protected readonly severity = statusSeverity;

  ngOnInit(): void {
    void this.reference();
    void this.load();
  }

  private async reference(): Promise<void> {
    const [locations, accounts] = await Promise.all([
      this.api.locations(),
      this.context.can('cash.view') ? this.finance.cashAccounts() : Promise.resolve([]),
    ]);
    this.locations.set(locations);
    this.accounts.set(accounts);
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.loadError.set(null);
    try {
      this.page.set(
        await this.api.list({
          status: SCOPES[this.scope],
          q: this.q.trim() || undefined,
          aging: this.aging,
          sort: this.sort,
          page: this.pageNo,
          page_size: PAGE_SIZE,
        }),
      );
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

  protected open(row: VehicleRow): void {
    void this.router.navigate(['/t', this.context.activeTenantId(), 'vehicles', row.id]);
  }

  protected label(row: VehicleRow): string {
    return [row.make, row.model, row.year].filter(Boolean).join(' ');
  }

  protected location(row: VehicleRow): string {
    return (this.language.language() === 'ar' ? row.location_name_ar : row.location_name_en) ?? '';
  }

  // --- Add-car wizard: details, then purchase (BACKLOG 4.5) ----------------------------
  protected onCreated(vehicle: Vehicle): void {
    this.created.set(vehicle);
    if (this.context.can('vehicle.purchase') && this.accounts().length > 0) {
      this.purchaseOpen.set(true);
    } else {
      void this.router.navigate(['/t', this.context.activeTenantId(), 'vehicles', vehicle.id]);
    }
  }

  protected afterPurchase(open: boolean): void {
    this.purchaseOpen.set(open);
    const vehicle = this.created();
    if (!open && vehicle) {
      this.created.set(null);
      void this.router.navigate(['/t', this.context.activeTenantId(), 'vehicles', vehicle.id]);
    }
  }
}
