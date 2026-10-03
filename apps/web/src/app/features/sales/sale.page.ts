import { Location } from '@angular/common';
import { Component, computed, inject, input, OnInit, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule, NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectModule } from 'primeng/select';
import { TagModule } from 'primeng/tag';

import { CashAccount, Preview, Sale, SaleDraftInput, ScheduleRow, Vehicle } from '../../core/api/api.models';
import { AppDatePipe, FormatService, MoneyPipe, PercentPipe } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { MoneyInputComponent } from '../../shared/components/money-input.component';
import { PostingPreviewComponent } from '../../shared/components/posting-preview.component';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { positiveMoney } from '../../shared/money-input';
import { moneyMinus, moneySum } from '../../shared/money-math';
import { CustomerPickerComponent } from '../customers/customer-picker.component';
import { loaded, translationsLoaded } from '../../shared/translated';
import { FinanceService } from '../finance/finance.service';
import { InstallmentsService } from '../installments/installments.service';
import { VehiclesService } from '../vehicles/vehicles.service';
import { CancelSaleDialogComponent } from './cancel-sale-dialog.component';
import { saleSeverity } from './sale-status';
import { SalesService } from './sales.service';

function optionalMoney(control: { value: string }): ReturnType<typeof positiveMoney> {
  return control.value ? positiveMoney(control as never) : null;
}

/**
 * New sale / sale record (SPEC §4.7, screens 6-7). Staff prepare a draft; an
 * owner or accountant posts it after a plain-language preview. Payments may
 * be split across cash and bank, a deposit is applied automatically, and the
 * buyer's own car can be taken as part payment (trade-in, rule 26).
 */
@Component({
  selector: 'app-sale-page',
  imports: [
    FormsModule,
    ReactiveFormsModule,
    RouterLink,
    TranslocoPipe,
    ButtonModule,
    CheckboxModule,
    DialogModule,
    InputTextModule,
    MessageModule,
    SelectModule,
    TagModule,
    MoneyPipe,
    AppDatePipe,
    PercentPipe,
    CanDirective,
    StateComponent,
    MoneyInputComponent,
    PostingPreviewComponent,
    CustomerPickerComponent,
    CancelSaleDialogComponent,
  ],
  templateUrl: './sale.page.html',
  styleUrl: './sale.page.scss',
})
export class SalePage implements OnInit {
  private readonly api = inject(SalesService);
  private readonly vehiclesApi = inject(VehiclesService);
  private readonly installmentsApi = inject(InstallmentsService);
  private readonly translations = translationsLoaded();
  private readonly finance = inject(FinanceService);
  private readonly router = inject(Router);
  private readonly location = inject(Location);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  private readonly format = inject(FormatService);
  private readonly fb = inject(NonNullableFormBuilder);
  protected readonly context = inject(TenantContextService);
  protected readonly language = inject(LanguageService);

  /** Route parameter (existing sale) and query parameters (new sale from a vehicle file). */
  readonly saleId = input<string>();
  readonly vehicle = input<string>();

  protected readonly sale = signal<Sale | null>(null);
  protected readonly car = signal<Vehicle | null>(null);
  protected readonly accounts = signal<CashAccount[]>([]);
  protected readonly vehicleOptions = signal<{ value: string; label: string }[]>([]);
  protected readonly loadError = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly preview = signal<Preview | null>(null);
  protected readonly postOpen = signal(false);
  protected readonly cancelOpen = signal(false);
  private postKey = crypto.randomUUID();

  protected readonly payments = this.fb.array([this.paymentRow()]);
  protected readonly form = this.fb.group({
    vehicle_id: ['', Validators.required],
    buyer_customer_id: ['', Validators.required],
    sale_date: ['', Validators.required],
    list_price: ['', [Validators.required, positiveMoney]],
    discount: ['', optionalMoney],
    has_trade_in: [false],
    trade_make: [''],
    trade_model: [''],
    trade_year: [''],
    trade_vin: [''],
    trade_plate: [''],
    trade_value: ['', optionalMoney],
    use_installments: [false],
    inst_count: ['6', Validators.pattern(/^\d{1,3}$/)],
    inst_frequency: ['MONTHLY' as 'MONTHLY' | 'BIWEEKLY' | 'WEEKLY' | 'QUARTERLY'],
    inst_first_due: [''],
    notes: [''],
    payments: this.payments,
  });
  protected readonly values = toSignal(this.form.valueChanges, { initialValue: this.form.getRawValue() });
  protected readonly accountOptions = computed(() =>
    this.accounts().map((a) => ({
      value: a.id,
      label: this.language.language() === 'ar' ? a.name_ar : (a.name_en ?? a.name_ar),
    })),
  );

  protected readonly severity = saleSeverity;
  protected readonly editable = computed(() => {
    const sale = this.sale();
    if (!sale) {
      return this.context.can('sale.draft');
    }
    return sale.status === 'DRAFT' && (sale.created_by_me || this.context.can('sale.post'));
  });
  /** The deposit applies when the car is reserved for this buyer. */
  protected readonly reservation = computed(() => {
    const r = this.car()?.reservation;
    return r && r.customer_id === this.values().buyer_customer_id ? r : null;
  });
  protected readonly reservedForOther = computed(() => {
    const r = this.car()?.reservation;
    return !!r && !!this.values().buyer_customer_id && r.customer_id !== this.values().buyer_customer_id;
  });
  protected readonly salePrice = computed(() => moneyMinus(this.values().list_price, this.values().discount));
  /** What payments, deposit and trade-in leave open. */
  private readonly open = computed(() => {
    const v = this.values();
    const paid = moneySum(...(v.payments ?? []).map((p) => p?.amount));
    const deposit = this.reservation()?.deposit_amount ?? this.sale()?.deposit_applied;
    return moneyMinus(this.salePrice(), paid, deposit, v.has_trade_in ? v.trade_value : '0');
  });
  /** Paid by installments (rule 13), when the plan is switched on. */
  protected readonly financed = computed(() =>
    this.values().use_installments && !this.open().startsWith('-') ? this.open() : '0.00',
  );
  protected readonly remaining = computed(() => moneyMinus(this.open(), this.financed()));
  protected readonly schedule = signal<ScheduleRow[]>([]);
  protected readonly installmentsEnabled = computed(() => this.context.flags()['installments'] === true);
  protected readonly frequencyOptions = computed(() => {
    if (!loaded(this.translations())) {
      return [];
    }
    return (['MONTHLY', 'BIWEEKLY', 'WEEKLY', 'QUARTERLY'] as const).map((value) => ({
      value,
      label: this.transloco.translate(`installments.frequency_${value}`),
    }));
  });
  protected readonly label = computed(() => {
    const v = this.car();
    return v ? [v.make, v.model, v.year].filter(Boolean).join(' ') : '';
  });

  ngOnInit(): void {
    void this.init();
  }

  private async init(): Promise<void> {
    try {
      if (this.context.can('cash.view')) {
        this.accounts.set(await this.finance.cashAccounts());
      }
      const id = this.saleId();
      if (id) {
        const sale = await this.api.get(id);
        this.sale.set(sale);
        this.fill(sale);
        this.car.set(await this.vehiclesApi.get(sale.vehicle_id));
      } else {
        this.form.patchValue({ sale_date: this.format.todayIso(), inst_first_due: this.nextMonth() });
        this.payments.at(0).patchValue({ cash_account_id: this.defaultAccount() });
        if (this.vehicle()) {
          await this.chooseVehicle(this.vehicle() as string);
        } else {
          const page = await this.vehiclesApi.list({ status: ['AVAILABLE', 'RESERVED'], page_size: 100, sort: 'make' });
          this.vehicleOptions.set(
            page.items.map((v) => ({ value: v.id, label: `${v.make} ${v.model} ${v.year ?? ''} — ${v.stock_no}` })),
          );
        }
      }
      if (!this.editable()) {
        this.form.disable();
      }
    } catch (error) {
      this.loadError.set(this.errors.message(error));
    }
  }

  protected async chooseVehicle(vehicleId: string): Promise<void> {
    const car = await this.vehiclesApi.get(vehicleId);
    this.car.set(car);
    this.form.patchValue({ vehicle_id: car.id, list_price: car.asking_price ?? '' });
    if (car.reservation && !this.form.controls.buyer_customer_id.value) {
      this.form.patchValue({ buyer_customer_id: car.reservation.customer_id });
    }
  }

  private nextMonth(): string {
    const [year, month, day] = this.format.todayIso().split('-').map(Number);
    return new Date(Date.UTC(year, month, Math.min(day, 28))).toISOString().slice(0, 10);
  }

  private paymentRow(cashAccountId = '', amount = '') {
    return this.fb.group({
      cash_account_id: [cashAccountId, Validators.required],
      amount: [amount, positiveMoney],
      reference: [''],
    });
  }

  private defaultAccount(): string {
    return this.accounts().find((a) => a.is_default)?.id ?? this.accounts()[0]?.id ?? '';
  }

  private fill(sale: Sale): void {
    this.payments.clear();
    for (const p of sale.payments) {
      this.payments.push(this.paymentRow(p.cash_account_id, p.amount));
    }
    this.form.patchValue({
      vehicle_id: sale.vehicle_id,
      buyer_customer_id: sale.buyer_customer_id ?? '',
      sale_date: sale.sale_date,
      list_price: sale.list_price,
      discount: sale.discount === '0.00' ? '' : sale.discount,
      has_trade_in: !!sale.trade_in,
      trade_make: sale.trade_in?.make ?? '',
      trade_model: sale.trade_in?.model ?? '',
      trade_year: sale.trade_in?.year ? String(sale.trade_in.year) : '',
      trade_vin: sale.trade_in?.vin ?? '',
      trade_plate: sale.trade_in?.plate_no ?? '',
      trade_value: sale.trade_in?.agreed_value ?? '',
      use_installments: !!sale.installment_plan,
      inst_count: String(sale.installment_plan?.count ?? 6),
      inst_frequency: (sale.installment_plan?.frequency ?? 'MONTHLY') as 'MONTHLY',
      inst_first_due: sale.installment_plan?.first_due_date ?? '',
      notes: sale.notes ?? '',
    });
    void this.refreshSchedule();
  }

  protected addPayment(): void {
    const remaining = this.remaining();
    this.payments.push(this.paymentRow(this.defaultAccount(), remaining.startsWith('-') ? '' : remaining));
  }

  protected removePayment(index: number): void {
    this.payments.removeAt(index);
  }

  /** Put whatever is still due on this payment line. */
  protected fillRemaining(index: number): void {
    const row = this.payments.at(index);
    row.patchValue({ amount: moneySum(row.controls.amount.value, this.remaining()) });
  }

  private body(): SaleDraftInput {
    const v = this.form.getRawValue();
    return {
      vehicle_id: v.vehicle_id,
      buyer_customer_id: v.buyer_customer_id,
      sale_date: v.sale_date,
      list_price: v.list_price,
      discount: v.discount || '0',
      reservation_id: this.reservation()?.id ?? null,
      payments: v.payments
        .filter((p) => p.amount && p.cash_account_id)
        .map((p) => ({ cash_account_id: p.cash_account_id, amount: p.amount, reference: p.reference.trim() || null })),
      trade_in: v.has_trade_in
        ? {
            make: v.trade_make.trim(),
            model: v.trade_model.trim(),
            year: v.trade_year ? Number(v.trade_year) : null,
            vin: v.trade_vin.trim() || null,
            plate_no: v.trade_plate.trim() || null,
            agreed_value: v.trade_value,
          }
        : null,
      installments: v.use_installments
        ? { frequency: v.inst_frequency, count: Number(v.inst_count), first_due_date: v.inst_first_due }
        : null,
      notes: v.notes.trim() || null,
    };
  }

  /** Show the schedule the API will create (equal split, remainder on the last installment). */
  protected async refreshSchedule(): Promise<void> {
    const v = this.form.getRawValue();
    if (!v.use_installments || this.financed() === '0.00' || !v.inst_first_due || !Number(v.inst_count)) {
      this.schedule.set([]);
      return;
    }
    try {
      this.schedule.set(
        await this.installmentsApi.schedulePreview(this.financed(), {
          frequency: v.inst_frequency,
          count: Number(v.inst_count),
          first_due_date: v.inst_first_due,
        }),
      );
      this.error.set(null);
    } catch (error) {
      this.schedule.set([]);
      this.error.set(this.errors.message(error));
    }
  }

  protected async save(): Promise<Sale | null> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return null;
    }
    return this.run(async () => {
      const existing = this.sale();
      const saved = existing ? await this.api.updateDraft(existing.id, this.body()) : await this.api.createDraft(this.body());
      this.sale.set(saved);
      if (!existing) {
        // Same screen, now for the saved draft: update the address without rebuilding the page.
        this.location.replaceState(`/t/${this.context.activeTenantId()}/sales/${saved.id}`);
      }
      this.toast.add({ severity: 'success', summary: this.transloco.translate('sales.saved') });
      return saved;
    });
  }

  protected async reviewPost(): Promise<void> {
    const saved = await this.save();
    if (!saved) {
      return;
    }
    await this.run(async () => {
      this.preview.set(await this.api.previewPost(saved.id));
      this.postKey = crypto.randomUUID();
      this.postOpen.set(true);
    });
  }

  protected async confirmPost(): Promise<void> {
    const sale = this.sale();
    if (!sale) {
      return;
    }
    await this.run(async () => {
      const result = await this.api.post(sale.id, this.postKey);
      this.postOpen.set(false);
      this.sale.set(result.document);
      this.form.disable();
      this.toast.add({
        severity: 'success',
        summary: this.transloco.translate('sales.postedToast', { invoice: result.document.invoice_no }),
      });
    });
  }

  protected async remove(): Promise<void> {
    const sale = this.sale();
    if (!sale) {
      return;
    }
    await this.run(async () => {
      await this.api.deleteDraft(sale.id);
      await this.router.navigate(['/t', this.context.activeTenantId(), 'sales']);
    });
  }

  protected async cancelled(): Promise<void> {
    const sale = this.sale();
    if (sale) {
      this.sale.set(await this.api.get(sale.id));
      this.toast.add({ severity: 'success', summary: this.transloco.translate('sales.cancelledToast') });
    }
  }

  protected async print(kind: 'invoice' | 'contract'): Promise<void> {
    const sale = this.sale();
    if (!sale) {
      return;
    }
    await this.run(async () => {
      const blob = await this.api.document(sale.id, kind, this.language.language());
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${kind}-${sale.invoice_no ?? sale.sale_no}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    });
  }

  private async run<T>(action: () => Promise<T>): Promise<T | null> {
    this.busy.set(true);
    this.error.set(null);
    try {
      return await action();
    } catch (error) {
      this.error.set(this.errors.message(error));
      return null;
    } finally {
      this.busy.set(false);
    }
  }
}
