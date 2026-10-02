import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule, NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { TableModule } from 'primeng/table';

import {
  CashAccount,
  Partner,
  PartnerPosting,
  PartnerSummary,
  PartnerSummaryRow,
  Share,
} from '../../core/api/api.models';
import { MoneyPipe, PercentPipe } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { FinanceService } from '../finance/finance.service';
import { PartnerTransactionDialogComponent } from './partner-transaction-dialog.component';
import { PartnersService } from './partners.service';
import { ShareChangeDialogComponent } from './share-change-dialog.component';

/**
 * Partners summary (SPEC §4.2): one row per partner — share, capital, profit,
 * drawings, current account, loans, net — answering "what is each partner's
 * balance?" in one screen (Phase 3 acceptance).
 */
@Component({
  selector: 'app-partners-page',
  imports: [
    FormsModule,
    ReactiveFormsModule,
    TranslocoPipe,
    ButtonModule,
    DialogModule,
    InputTextModule,
    MessageModule,
    TableModule,
    MoneyPipe,
    PercentPipe,
    CanDirective,
    StateComponent,
    PartnerTransactionDialogComponent,
    ShareChangeDialogComponent,
  ],
  templateUrl: './partners.page.html',
  styleUrl: './partners.page.scss',
})
export class PartnersPage implements OnInit {
  private readonly api = inject(PartnersService);
  private readonly finance = inject(FinanceService);
  private readonly context = inject(TenantContextService);
  private readonly router = inject(Router);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  protected readonly language = inject(LanguageService);

  protected readonly state = signal<'loading' | 'ready' | 'error'>('loading');
  protected readonly loadError = signal<string | null>(null);
  protected readonly summary = signal<PartnerSummary | null>(null);
  protected readonly partners = signal<Partner[]>([]);
  protected readonly shares = signal<Share[]>([]);
  protected readonly accounts = signal<CashAccount[]>([]);

  protected readonly txnOpen = signal(false);
  protected readonly sharesOpen = signal(false);
  protected readonly addOpen = signal(false);
  protected readonly addBusy = signal(false);
  protected readonly addError = signal<string | null>(null);
  protected readonly addForm = inject(NonNullableFormBuilder).group({
    name_ar: ['', Validators.required],
    name_en: [''],
    phone: [''],
    national_id: ['', Validators.pattern(/^[0-9A-Za-z]{4,20}$/)],
  });

  ngOnInit(): void {
    // A partner user without access to everyone goes straight to their own statement.
    const own = this.context.active()?.partner_id;
    if (!this.context.can('partner.view_all') && own) {
      void this.router.navigate(['/t', this.context.activeTenantId(), 'partners', own], { replaceUrl: true });
      return;
    }
    void this.load();
  }

  protected async load(): Promise<void> {
    try {
      const [summary, partners, shares, accounts] = await Promise.all([
        this.api.summary(),
        this.api.list(),
        this.api.shares(),
        this.context.can('cash.view') ? this.finance.cashAccounts() : Promise.resolve([]),
      ]);
      this.summary.set(summary);
      this.partners.set(partners);
      this.shares.set(shares);
      this.accounts.set(accounts);
      this.state.set('ready');
    } catch (error) {
      this.loadError.set(this.errors.message(error));
      this.state.set('error');
    }
  }

  protected name(row: { name_ar: string; name_en?: string | null }): string {
    return this.language.language() === 'ar' ? row.name_ar : (row.name_en ?? row.name_ar);
  }

  protected open(row: PartnerSummaryRow): void {
    void this.router.navigate(['/t', this.context.activeTenantId(), 'partners', row.partner_id]);
  }

  protected negative(value: string): boolean {
    return value.startsWith('-');
  }

  protected async onPosted(result: PartnerPosting): Promise<void> {
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

  protected openAdd(): void {
    this.addForm.reset({ name_ar: '', name_en: '', phone: '', national_id: '' });
    this.addError.set(null);
    this.addOpen.set(true);
  }

  protected async saveAdd(): Promise<void> {
    if (this.addForm.invalid) {
      return;
    }
    const v = this.addForm.getRawValue();
    this.addBusy.set(true);
    this.addError.set(null);
    try {
      await this.api.create({
        name_ar: v.name_ar.trim(),
        name_en: v.name_en.trim() || null,
        phone: v.phone.trim() || null,
        national_id: v.national_id.trim() || null,
      });
      this.addOpen.set(false);
      this.toast.add({ severity: 'info', summary: this.transloco.translate('partners.addedHint') });
      await this.load();
    } catch (error) {
      this.addError.set(this.errors.message(error));
    } finally {
      this.addBusy.set(false);
    }
  }
}
