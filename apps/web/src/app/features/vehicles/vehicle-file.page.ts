import { Component, computed, inject, input, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';

import {
  CashAccount,
  DocumentType,
  ExpenseCategory,
  Location,
  Partner,
  PostingWarning,
  Supplier,
  Vehicle,
  VehicleStatus,
} from '../../core/api/api.models';
import { AppDatePipe, FormatService, MoneyPipe, PercentPipe } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { compressImage } from '../../shared/image-compress';
import { FinanceService } from '../finance/finance.service';
import { ConsignOutDialogComponent } from '../consignment/consign-out-dialog.component';
import { ConsignmentService } from '../consignment/consignment.service';
import { ExternalSaleDialogComponent } from '../consignment/external-sale-dialog.component';
import { PartnersService } from '../partners/partners.service';
import { VehicleMatchesComponent } from '../requests/vehicle-matches.component';
import { ReservationDialogComponent } from '../sales/reservation-dialog.component';
import { SettleDialogComponent } from '../sales/settle-dialog.component';
import { SuppliersService } from '../suppliers/suppliers.service';
import { PaymentDialogComponent } from './payment-dialog.component';
import { PurchaseDialogComponent } from './purchase-dialog.component';
import { VehicleExpenseDialogComponent } from './vehicle-expense-dialog.component';
import { statusSeverity } from './vehicle-status';
import { VehicleFormDialogComponent } from './vehicle-form-dialog.component';
import { VehiclesService } from './vehicles.service';

/** Moves a user may make directly (mirrors MANUAL_TRANSITIONS in the API). */
const NEXT: Partial<Record<VehicleStatus, VehicleStatus[]>> = {
  DRAFT: ['IN_PREPARATION', 'ARCHIVED'],
  IN_PREPARATION: ['AVAILABLE', 'ARCHIVED'],
  AVAILABLE: ['ARCHIVED'],
  SOLD: ['DELIVERED'],
};
const DOC_TYPES: DocumentType[] = [
  'LICENSE',
  'POWER_OF_ATTORNEY',
  'PURCHASE_CONTRACT',
  'SALE_CONTRACT',
  'ID_COPY',
  'INSPECTION_REPORT',
  'SELLER_RECEIPT',
  'OTHER',
];

/**
 * The vehicle file (ملف العربية, SPEC §4.3): everything about one car on one
 * screen — details, photos, documents, history, and for users who may see
 * cost, the full cost breakdown and the profit after sale.
 */
@Component({
  selector: 'app-vehicle-file-page',
  imports: [
    FormsModule,
    RouterLink,
    TranslocoPipe,
    ButtonModule,
    DialogModule,
    InputTextModule,
    SelectModule,
    TableModule,
    TagModule,
    MoneyPipe,
    AppDatePipe,
    PercentPipe,
    CanDirective,
    StateComponent,
    VehicleFormDialogComponent,
    VehicleExpenseDialogComponent,
    PurchaseDialogComponent,
    PaymentDialogComponent,
    ReservationDialogComponent,
    SettleDialogComponent,
    ConsignOutDialogComponent,
    ExternalSaleDialogComponent,
    VehicleMatchesComponent,
  ],
  templateUrl: './vehicle-file.page.html',
  styleUrl: './vehicle-file.page.scss',
})
export class VehicleFilePage implements OnInit {
  private readonly api = inject(VehiclesService);
  private readonly finance = inject(FinanceService);
  private readonly partnersApi = inject(PartnersService);
  private readonly suppliersApi = inject(SuppliersService);
  private readonly consignmentApi = inject(ConsignmentService);
  private readonly format = inject(FormatService);
  private readonly router = inject(Router);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  protected readonly context = inject(TenantContextService);
  protected readonly language = inject(LanguageService);

  readonly vehicleId = input.required<string>();

  protected readonly vehicle = signal<Vehicle | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly accounts = signal<CashAccount[]>([]);
  protected readonly categories = signal<ExpenseCategory[]>([]);
  protected readonly suppliers = signal<Supplier[]>([]);
  protected readonly partners = signal<Partner[]>([]);
  protected readonly locations = signal<Location[]>([]);
  protected readonly uploading = signal(false);

  protected readonly editOpen = signal(false);
  protected readonly expenseOpen = signal(false);
  protected readonly purchaseOpen = signal(false);
  protected readonly sellerPayOpen = signal(false);
  protected readonly reserveOpen = signal(false);
  protected readonly settleOpen = signal(false);
  protected readonly moveOpen = signal(false);
  protected readonly sendOutOpen = signal(false);
  protected readonly externalSaleOpen = signal(false);
  protected moveTo = '';
  protected moveReason = '';
  protected docType: DocumentType = 'LICENSE';

  protected readonly severity = statusSeverity;
  protected readonly docTypes = DOC_TYPES;
  protected readonly label = computed(() => {
    const v = this.vehicle();
    return v ? [v.make, v.model, v.trim, v.year].filter(Boolean).join(' ') : '';
  });
  protected readonly nextStatuses = computed(() => {
    const v = this.vehicle();
    const next = NEXT[v?.status ?? 'ARCHIVED'] ?? [];
    // A consigned car leaves by going back to its owner, never by archiving.
    return v?.ownership_type === 'CONSIGNED_IN' ? next.filter((s) => s !== 'ARCHIVED') : next;
  });
  protected readonly canSell = computed(() => ['AVAILABLE', 'RESERVED'].includes(this.vehicle()?.status ?? ''));
  protected readonly locationOptions = computed(() =>
    this.locations().map((l) => ({ value: l.id, label: this.language.language() === 'ar' ? l.name_ar : (l.name_en ?? l.name_ar) })),
  );

  ngOnInit(): void {
    void this.load();
    void this.reference();
  }

  protected async load(): Promise<void> {
    try {
      this.vehicle.set(await this.api.get(this.vehicleId()));
      this.loadError.set(null);
    } catch (error) {
      this.loadError.set(this.errors.message(error));
    }
  }

  private async reference(): Promise<void> {
    const can = (p: string) => this.context.can(p);
    const [accounts, categories, suppliers, partners, locations] = await Promise.all([
      can('cash.view') ? this.finance.cashAccounts() : Promise.resolve([]),
      can('vehicle.expense.record') ? this.finance.categories('VEHICLE') : Promise.resolve([]),
      can('supplier.manage') ? this.suppliersApi.list() : Promise.resolve([]),
      can('partner.view_all') ? this.partnersApi.list() : Promise.resolve([]),
      this.api.locations(),
    ]);
    this.accounts.set(accounts);
    this.categories.set(categories);
    this.suppliers.set(suppliers);
    this.partners.set(partners);
    this.locations.set(locations);
  }

  protected name(item: { name_ar: string | null; name_en?: string | null } | null | undefined): string {
    if (!item) {
      return '';
    }
    return (this.language.language() === 'ar' ? item.name_ar : (item.name_en ?? item.name_ar)) ?? '';
  }

  protected location(v: Vehicle): string {
    return (this.language.language() === 'ar' ? v.location_name_ar : v.location_name_en) ?? '';
  }

  protected async setStatus(status: VehicleStatus): Promise<void> {
    await this.act(async () => this.vehicle.set(await this.api.setStatus(this.vehicleId(), status)));
  }

  protected async move(): Promise<void> {
    if (!this.moveTo) {
      return;
    }
    await this.act(async () => {
      this.vehicle.set(await this.api.move(this.vehicleId(), this.moveTo, this.moveReason));
      this.moveOpen.set(false);
    });
  }

  protected sell(): void {
    void this.router.navigate(['/t', this.context.activeTenantId(), 'sales', 'new'], {
      queryParams: { vehicle: this.vehicleId(), reservation: this.vehicle()?.reservation?.id },
    });
  }

  protected async onPosted(result: { journal_entries: { entry_no: number }[]; warnings?: PostingWarning[] }): Promise<void> {
    this.toast.add({
      severity: 'success',
      summary: this.transloco.translate('finance.posted', { entryNo: result.journal_entries[0]?.entry_no }),
    });
    for (const warning of result.warnings ?? []) {
      const details = warning.details ?? {};
      this.toast.add({
        severity: 'warn',
        summary: this.transloco.translate(`warnings.${warning.code}`, {
          name: this.language.language() === 'ar' ? details['name_ar'] : details['name_en'],
          balanceAfter: details['balance_after'],
        }),
      });
    }
    await this.load();
  }

  protected async sentOut(): Promise<void> {
    this.toast.add({ severity: 'success', summary: this.transloco.translate('consignment.sentOutToast') });
    await this.load();
  }

  protected async cameBack(outId: string): Promise<void> {
    await this.act(async () => {
      await this.consignmentApi.returnOut(outId, this.format.todayIso(), null);
      await this.load();
    });
  }

  protected async onPaid(): Promise<void> {
    this.toast.add({ severity: 'success', summary: this.transloco.translate('finance.postedShort') });
    await this.load();
  }

  // --- Photos (camera capture, compressed in the browser) and documents ------------------
  protected async addPhotos(event: Event): Promise<void> {
    const files = Array.from((event.target as HTMLInputElement).files ?? []);
    (event.target as HTMLInputElement).value = '';
    if (files.length === 0) {
      return;
    }
    this.uploading.set(true);
    await this.act(async () => {
      for (const file of files) {
        await this.api.uploadPhoto(this.vehicleId(), await compressImage(file));
      }
      await this.load();
    });
    this.uploading.set(false);
  }

  protected async removePhoto(mediaId: string): Promise<void> {
    await this.act(async () => {
      await this.api.removePhoto(this.vehicleId(), mediaId);
      await this.load();
    });
  }

  protected async addDocument(event: Event): Promise<void> {
    const file = (event.target as HTMLInputElement).files?.[0];
    (event.target as HTMLInputElement).value = '';
    if (!file) {
      return;
    }
    this.uploading.set(true);
    await this.act(async () => {
      await this.api.uploadDocument(this.vehicleId(), this.docType, file);
      await this.load();
    });
    this.uploading.set(false);
  }

  protected async openDocument(documentId: string): Promise<void> {
    await this.act(async () => {
      const { url } = await this.api.documentUrl(documentId);
      window.open(url, '_blank', 'noopener');
    });
  }

  protected docTypeAllowed(type: DocumentType): boolean {
    return !['PURCHASE_CONTRACT', 'SELLER_RECEIPT'].includes(type) || this.context.can('vehicle.view_cost');
  }

  private async act(action: () => Promise<void>): Promise<void> {
    try {
      await action();
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    }
  }
}
