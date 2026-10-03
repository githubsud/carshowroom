import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';

import { ImportJob, ImportPosting } from '../../core/api/api.models';
import { FormatService } from '../../core/format/format.service';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { ErrorMessageService } from '../../shared/error-message.service';
import { ImportReviewComponent } from './import-review.component';
import { fileToBase64, ImportsService } from './imports.service';
import { OpeningEquityComponent } from './opening-equity.component';

type Step = 'profile' | 'partners' | 'cash' | 'stock' | 'review' | 'done';
const STEPS: Step[] = ['profile', 'partners', 'cash', 'stock', 'review', 'done'];

interface PartnerRow {
  name: string;
  percentage: string;
  capital: string;
}
interface CashRow {
  name: string;
  kind: 'CASH_BOX' | 'BANK';
  balance: string;
}

/**
 * Onboarding (SPEC §4.1): profile → partners and capital → cash and bank
 * openings → stock from Excel → one opening entry at go-live (D-110).
 */
@Component({
  selector: 'app-onboarding-page',
  imports: [FormsModule, TranslocoPipe, ButtonModule, InputTextModule, MessageModule, ImportReviewComponent, OpeningEquityComponent],
  template: `
    <h1 class="page-title">{{ 'onboarding.title' | transloco }}</h1>
    <ol class="steps" aria-label="steps">
      @for (s of steps; track s; let i = $index) {
        <li [class.active]="s === step()" [class.past]="i < index()">{{ i + 1 }}. {{ 'onboarding.step_' + s | transloco }}</li>
      }
    </ol>

    @switch (step()) {
      @case ('profile') {
        <section class="card dialog-fields" data-testid="onb-profile">
          <div class="field"><label for="p-name">{{ 'onboarding.nameAr' | transloco }}</label>
            <input pInputText id="p-name" [(ngModel)]="profile.name_ar" data-testid="onb-name" /></div>
          <div class="field"><label for="p-name-en">{{ 'onboarding.nameEn' | transloco }}</label>
            <input pInputText id="p-name-en" [(ngModel)]="profile.name_en" dir="ltr" /></div>
          <div class="field"><label for="p-phone">{{ 'customers.phone' | transloco }}</label>
            <input pInputText id="p-phone" [(ngModel)]="profile.phone" dir="ltr" inputmode="tel" /></div>
          <div class="field"><label for="p-address">{{ 'customers.address' | transloco }}</label>
            <input pInputText id="p-address" [(ngModel)]="profile.address" /></div>
          <div class="field"><label for="p-cr">{{ 'onboarding.cr' | transloco }}</label>
            <input pInputText id="p-cr" [(ngModel)]="profile.cr" dir="ltr" /></div>
        </section>
      }
      @case ('partners') {
        <section class="card" data-testid="onb-partners">
          <p class="sub">{{ 'onboarding.partnersHint' | transloco }}</p>
          <table class="rows">
            <thead><tr><th>{{ 'customers.name' | transloco }}</th><th>%</th><th>{{ 'partners.capital' | transloco }}</th><th></th></tr></thead>
            <tbody>
              @for (row of partnerRows; track $index; let i = $index) {
                <tr>
                  <td><input pInputText [(ngModel)]="row.name" [attr.data-testid]="'onb-partner-name-' + i" [attr.aria-label]="'customers.name' | transloco" /></td>
                  <td><input pInputText class="short" [(ngModel)]="row.percentage" inputmode="decimal" dir="ltr"
                             [attr.data-testid]="'onb-partner-pct-' + i" aria-label="%" /></td>
                  <td><input pInputText [(ngModel)]="row.capital" inputmode="decimal" dir="ltr"
                             [attr.data-testid]="'onb-partner-capital-' + i" [attr.aria-label]="'partners.capital' | transloco" /></td>
                  <td><p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="partnerRows.splice(i, 1)"
                                [ariaLabel]="'common.cancel' | transloco" /></td>
                </tr>
              }
            </tbody>
          </table>
          <p-button icon="pi pi-plus" [text]="true" [label]="'onboarding.addPartner' | transloco" (onClick)="addPartner()"
                    data-testid="onb-add-partner" />
          <p [class.negative]="shareTotal() !== 100">{{ 'onboarding.shareTotal' | transloco: { n: shareTotal() } }}</p>
        </section>
      }
      @case ('cash') {
        <section class="card" data-testid="onb-cash">
          <p class="sub">{{ 'onboarding.cashHint' | transloco }}</p>
          <table class="rows">
            <tbody>
              @for (row of cashRows; track $index; let i = $index) {
                <tr>
                  <td><input pInputText [(ngModel)]="row.name" [attr.data-testid]="'onb-cash-name-' + i" [attr.aria-label]="'customers.name' | transloco" /></td>
                  <td><select [(ngModel)]="row.kind" [attr.aria-label]="'imports.kind' | transloco">
                    <option value="CASH_BOX">{{ 'onboarding.cashBox' | transloco }}</option>
                    <option value="BANK">{{ 'onboarding.bank' | transloco }}</option></select></td>
                  <td><input pInputText [(ngModel)]="row.balance" inputmode="decimal" dir="ltr"
                             [attr.data-testid]="'onb-cash-balance-' + i" [attr.aria-label]="'finance.amount' | transloco" /></td>
                  <td><p-button icon="pi pi-trash" [text]="true" severity="danger" (onClick)="cashRows.splice(i, 1)"
                                [ariaLabel]="'common.cancel' | transloco" /></td>
                </tr>
              }
            </tbody>
          </table>
          <p-button icon="pi pi-plus" [text]="true" [label]="'onboarding.addAccount' | transloco" (onClick)="addCash()" />
        </section>
      }
      @case ('stock') {
        <section class="card dialog-fields" data-testid="onb-stock">
          <div class="field"><label for="go-live">{{ 'imports.goLive' | transloco }}</label>
            <input pInputText id="go-live" type="date" [(ngModel)]="goLive" /></div>
          <p class="sub">{{ 'onboarding.stockHint' | transloco }}</p>
          <label class="file">
            <i class="pi pi-upload" aria-hidden="true"></i> {{ file ? file.name : ('imports.chooseFile' | transloco) }}
            <input type="file" accept=".xlsx,.csv" (change)="chooseFile($event)" hidden data-testid="onb-file" />
          </label>
        </section>
      }
      @case ('review') {
        @if (job(); as j) {
          <app-import-review [job]="j" (changed)="job.set($event)" (committed)="committed($event)" />
        }
      }
      @case ('done') {
        <section class="card" data-testid="onb-done">
          <h2><i class="pi pi-check-circle" aria-hidden="true"></i> {{ 'onboarding.ready' | transloco }}</h2>
          @if (posting()?.journal_entries?.length) {
            <p>{{ 'imports.entry' | transloco: { n: posting()?.journal_entries?.[0]?.entry_no } }}</p>
          }
        </section>
        <app-opening-equity />
        <p-button [label]="'onboarding.toDashboard' | transloco" (onClick)="finish()" data-testid="onb-finish" />
      }
    }

    @if (error()) { <p-message severity="error" data-testid="onb-error">{{ error() }}</p-message> }
    @if (step() !== 'review' && step() !== 'done') {
      <div class="nav">
        @if (index() > 0) { <p-button [text]="true" [label]="'onboarding.back' | transloco" (onClick)="back()" /> }
        <p-button [label]="'onboarding.next' | transloco" (onClick)="next()" [loading]="busy()" data-testid="onb-next" />
      </div>
    }
  `,
  styles: `
    .steps {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      padding: 0;
      margin: 0 0 var(--space-3);
      list-style: none;

      li {
        padding: var(--space-1) var(--space-3);
        font-size: 0.85rem;
        border: 1px solid var(--color-border);
        border-radius: 999px;
      }
      li.active {
        font-weight: 700;
        color: #fff;
        background: var(--p-primary-color, #1d4ed8);
      }
      li.past {
        color: var(--color-text-muted);
      }
    }
    .rows td,
    .rows th {
      padding: var(--space-1);
      text-align: start;
    }
    .short {
      inline-size: 80px;
    }
    .file {
      display: inline-flex;
      gap: var(--space-2);
      align-items: center;
      padding: var(--space-4);
      cursor: pointer;
      border: 2px dashed var(--color-border);
      border-radius: 8px;
    }
    .nav {
      display: flex;
      gap: var(--space-2);
      justify-content: flex-end;
      margin-block-start: var(--space-3);
    }
  `,
})
export class OnboardingPage implements OnInit {
  private readonly api = inject(ImportsService);
  private readonly context = inject(TenantContextService);
  private readonly errors = inject(ErrorMessageService);
  private readonly format = inject(FormatService);
  private readonly router = inject(Router);

  protected readonly steps = STEPS;
  protected readonly step = signal<Step>('profile');
  protected readonly index = computed(() => STEPS.indexOf(this.step()));
  protected readonly job = signal<ImportJob | null>(null);
  protected readonly posting = signal<ImportPosting | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected profile = { name_ar: '', name_en: '', phone: '', address: '', cr: '' };
  protected partnerRows: PartnerRow[] = [{ name: '', percentage: '100', capital: '' }];
  protected cashRows: CashRow[] = [];
  protected goLive = '';
  protected file: File | null = null;

  protected readonly shareTotal = signal(100);

  ngOnInit(): void {
    const tenant = this.context.tenant();
    const profile = tenant?.profile;
    this.profile = {
      name_ar: profile?.name_ar ?? '',
      name_en: profile?.name_en ?? '',
      phone: profile?.phones?.[0] ?? '',
      address: profile?.address ?? '',
      cr: profile?.commercial_reg_no ?? '',
    };
    this.cashRows = [
      { name: 'الخزنة الرئيسية', kind: 'CASH_BOX', balance: '' },
      { name: '', kind: 'BANK', balance: '' },
    ];
    this.goLive = this.format.todayIso();
  }

  protected addPartner(): void {
    this.partnerRows.push({ name: '', percentage: '', capital: '' });
  }

  protected addCash(): void {
    this.cashRows.push({ name: '', kind: 'BANK', balance: '' });
  }

  protected chooseFile(event: Event): void {
    this.file = (event.target as HTMLInputElement).files?.[0] ?? null;
  }

  protected back(): void {
    this.error.set(null);
    this.step.set(STEPS[Math.max(0, this.index() - 1)]);
  }

  protected async next(): Promise<void> {
    this.error.set(null);
    this.busy.set(true);
    try {
      switch (this.step()) {
        case 'profile':
          await this.context.updateProfile({
            name_ar: this.profile.name_ar.trim(),
            name_en: this.profile.name_en.trim() || null,
            address: this.profile.address.trim() || null,
            commercial_reg_no: this.profile.cr.trim() || null,
            phones: this.profile.phone.trim() ? [this.profile.phone.trim()] : [],
          });
          break;
        case 'partners':
          this.shareTotal.set(this.partnerRows.filter((r) => r.name.trim()).reduce((sum, r) => sum + Number(r.percentage || 0), 0));
          break;
        case 'stock':
          this.job.set(await this.createJob());
          break;
      }
      this.step.set(STEPS[this.index() + 1]);
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }

  private async createJob(): Promise<ImportJob> {
    const partners = this.partnerRows.filter((r) => r.name.trim());
    const cash = this.cashRows.filter((r) => r.name.trim() && r.balance.trim());
    const sheets = [];
    if (partners.length) {
      sheets.push({
        name: 'الشركاء',
        kind: 'PARTNERS' as const,
        headers: ['name', 'percentage', 'capital'],
        rows: partners.map((r) => [r.name.trim(), r.percentage, r.capital.trim() || null]),
      });
    }
    if (cash.length) {
      sheets.push({
        name: 'الخزنة والبنوك',
        kind: 'CASH' as const,
        headers: ['account_name', 'account_type', 'balance'],
        rows: cash.map((r) => [r.name.trim(), r.kind === 'BANK' ? 'bank' : 'cash', r.balance]),
      });
    }
    return this.api.create({
      go_live_date: this.goLive,
      file_name: this.file?.name ?? null,
      content_base64: this.file ? await fileToBase64(this.file) : null,
      sheets,
    });
  }

  protected committed(posting: ImportPosting): void {
    this.posting.set(posting);
    this.step.set('done');
  }

  protected finish(): void {
    void this.router.navigate(['/t', this.context.activeTenantId(), 'dashboard']);
  }
}
