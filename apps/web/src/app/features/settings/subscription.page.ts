import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { TagModule } from 'primeng/tag';

import { Branch, SupportGrant, Usage } from '../../core/api/api.models';
import { AppDatePipe } from '../../core/format/format.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { saveBlob } from '../../shared/download';
import { ErrorMessageService } from '../../shared/error-message.service';
import { PlatformService } from '../admin/platform.service';

/** Settings → Subscription: plan usage, branches, support access and the full data export. */
@Component({
  selector: 'app-subscription-page',
  imports: [FormsModule, TranslocoPipe, ButtonModule, InputTextModule, MessageModule, TagModule, AppDatePipe, CanDirective],
  template: `
    <div class="page-header"><h1 class="page-title">{{ 'subscription.pageTitle' | transloco }}</h1></div>

    @if (usage(); as u) {
      <section class="card" data-testid="usage">
        <h2>{{ 'subscription.plan' | transloco }}: {{ u.plan_code }}
          <p-tag [value]="'subscription.' + (context.active()?.subscription_status ?? '') | transloco" /></h2>
        @for (key of limitKeys; track key) {
          <div class="meter">
            <span>{{ 'subscription.limit_' + key | transloco }}</span>
            <span dir="ltr">{{ u.used[key] }} / {{ u.limits[key] ?? '∞' }}</span>
            <span class="bar"><span [style.inline-size.%]="percent(u, key)"></span></span>
          </div>
        }
      </section>
    }

    <section class="card" *appCan="'tenant.settings.manage'">
      <h2>{{ 'subscription.branches' | transloco }}</h2>
      <ul class="list">
        @for (b of branches(); track b.id) {
          <li>{{ b.name_ar }} @if (b.is_default) { <p-tag severity="secondary" [value]="'subscription.main' | transloco" /> }</li>
        }
      </ul>
      <div class="row">
        <input pInputText [(ngModel)]="branchName" [placeholder]="'customers.name' | transloco"
               [attr.aria-label]="'customers.name' | transloco" data-testid="branch-name" />
        <p-button [outlined]="true" icon="pi pi-plus" [label]="'subscription.addBranch' | transloco" (onClick)="addBranch()"
                  [disabled]="!branchName.trim()" data-testid="branch-add" />
      </div>
    </section>

    <section class="card" *appCan="'support.grant'" data-testid="support-access">
      <h2>{{ 'subscription.support' | transloco }}</h2>
      <p class="sub">{{ 'subscription.supportHint' | transloco }}</p>
      <div class="row">
        <select [(ngModel)]="hours" [attr.aria-label]="'subscription.hours' | transloco">
          @for (h of [1, 4, 24, 72]; track h) { <option [ngValue]="h">{{ 'subscription.hoursN' | transloco: { n: h } }}</option> }
        </select>
        <input pInputText [(ngModel)]="reason" [placeholder]="'vehicles.reason' | transloco"
               [attr.aria-label]="'vehicles.reason' | transloco" data-testid="grant-reason" />
        <p-button [label]="'subscription.grant' | transloco" (onClick)="grant()" [disabled]="reason.trim().length < 3"
                  data-testid="grant-support" />
      </div>
      <ul class="list" data-testid="grants">
        @for (g of grants(); track g.id) {
          <li>
            {{ g.reason }} · {{ g.starts_at | appDate }} → {{ g.expires_at | appDate }}
            @if (g.active) {
              <p-tag severity="success" [value]="'subscription.active' | transloco" />
              <p-button [text]="true" severity="danger" size="small" [label]="'subscription.revoke' | transloco"
                        (onClick)="revoke(g)" data-testid="revoke-support" />
            } @else { <p-tag severity="secondary" [value]="'subscription.ended' | transloco" /> }
          </li>
        }
      </ul>
    </section>

    <section class="card" *appCan="'tenant.settings.manage'">
      <h2>{{ 'subscription.export' | transloco }}</h2>
      <p class="sub">{{ 'subscription.exportHint' | transloco }}</p>
      <p-button icon="pi pi-download" [outlined]="true" [label]="'subscription.exportNow' | transloco" (onClick)="export()"
                [loading]="exporting()" data-testid="export" />
    </section>
    @if (error()) { <p-message severity="error">{{ error() }}</p-message> }
  `,
  styles: `
    .meter {
      display: grid;
      grid-template-columns: 1fr auto 140px;
      gap: var(--space-2);
      align-items: center;
      padding-block: var(--space-1);
    }
    .bar {
      block-size: 8px;
      overflow: hidden;
      background: var(--color-border);
      border-radius: 4px;

      span {
        display: block;
        block-size: 100%;
        background: var(--p-primary-color, #1d4ed8);
      }
    }
    .row {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      align-items: center;
    }
    .list {
      padding: 0;
      list-style: none;

      li {
        display: flex;
        flex-wrap: wrap;
        gap: var(--space-2);
        align-items: center;
        padding-block: var(--space-1);
      }
    }
  `,
})
export class SubscriptionPage implements OnInit {
  private readonly api = inject(PlatformService);
  private readonly errors = inject(ErrorMessageService);
  protected readonly context = inject(TenantContextService);

  protected readonly limitKeys = ['users', 'branches', 'vehicles_in_stock'];
  protected readonly usage = signal<Usage | null>(null);
  protected readonly branches = signal<Branch[]>([]);
  protected readonly grants = signal<SupportGrant[]>([]);
  protected readonly exporting = signal(false);
  protected readonly error = signal<string | null>(null);
  protected branchName = '';
  protected hours = 4;
  protected reason = '';

  ngOnInit(): void {
    if (this.context.can('tenant.settings.manage')) {
      void this.api.usage().then((u) => this.usage.set(u));
      void this.api.branches().then((b) => this.branches.set(b));
    }
    if (this.context.can('support.grant')) {
      void this.api.grants().then((g) => this.grants.set(g));
    }
  }

  protected percent(usage: Usage, key: string): number {
    const limit = usage.limits[key];
    return limit ? Math.min(100, ((usage.used[key] ?? 0) / limit) * 100) : 0;
  }

  protected async addBranch(): Promise<void> {
    await this.run(async () => {
      await this.api.addBranch({ name_ar: this.branchName.trim(), name_en: null, address: null });
      this.branchName = '';
      this.branches.set(await this.api.branches());
      this.usage.set(await this.api.usage());
    });
  }

  protected async grant(): Promise<void> {
    await this.run(async () => {
      await this.api.grant(this.hours, this.reason.trim());
      this.reason = '';
      this.grants.set(await this.api.grants());
    });
  }

  protected async revoke(grant: SupportGrant): Promise<void> {
    await this.run(async () => {
      await this.api.revoke(grant.id);
      this.grants.set(await this.api.grants());
    });
  }

  protected async export(): Promise<void> {
    this.exporting.set(true);
    await this.run(async () => saveBlob(await this.api.export(), 'sayyara-export.zip'));
    this.exporting.set(false);
  }

  private async run(action: () => Promise<void>): Promise<void> {
    this.error.set(null);
    try {
      await action();
    } catch (error) {
      this.error.set(this.errors.message(error));
    }
  }
}
