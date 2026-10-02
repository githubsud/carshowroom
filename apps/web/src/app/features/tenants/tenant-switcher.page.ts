import { Component, inject, OnInit, signal } from '@angular/core';
import { Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { TagModule } from 'primeng/tag';

import { Membership } from '../../core/api/api.models';
import { AuthService } from '../../core/auth/auth.service';
import { LanguageService } from '../../core/i18n/language.service';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';

/**
 * Choose a showroom. Skipped automatically when the user has one membership
 * (or a still-valid last choice).
 */
@Component({
  selector: 'app-tenant-switcher-page',
  imports: [TranslocoPipe, ButtonModule, TagModule, StateComponent],
  template: `
    <div class="card">
      <h1>{{ 'tenants.title' | transloco }}</h1>

      @if (state() === 'loading') {
        <app-state kind="loading" />
      } @else if (state() === 'error') {
        <app-state kind="error" [message]="error()" (retry)="load(true)" />
      } @else if (context.memberships().length === 0) {
        <app-state kind="empty" [message]="'tenants.none' | transloco" />
      } @else {
        <ul class="tenant-list" data-testid="tenant-list">
          @for (membership of context.memberships(); track membership.tenant_id) {
            <li>
              <button type="button" class="tenant" (click)="open(membership)" [attr.data-testid]="'tenant-' + membership.tenant_id">
                <span class="name">{{ name(membership) }}</span>
                <span class="meta">
                  <p-tag [value]="'roles.' + membership.role_code | transloco" severity="secondary" />
                  <span>{{ membership.currency_code }}</span>
                  @if (membership.tenant_id === context.lastUsedTenantId()) {
                    <span>· {{ 'tenants.lastUsed' | transloco }}</span>
                  }
                </span>
              </button>
            </li>
          }
        </ul>
      }

      <p-button type="button" [text]="true" icon="pi pi-sign-out" [label]="'shell.signOut' | transloco" (onClick)="signOut()" />
    </div>
  `,
  styleUrl: '../auth/auth-layout.scss',
  styles: `
    .tenant-list {
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
      padding: 0;
      margin-block: var(--space-3);
      list-style: none;
    }

    .tenant {
      display: flex;
      flex-direction: column;
      gap: var(--space-1);
      inline-size: 100%;
      min-block-size: 56px;
      padding: var(--space-3);
      font: inherit;
      color: var(--color-text);
      text-align: start;
      cursor: pointer;
      background: var(--color-surface);
      border: 1px solid var(--color-border);
      border-radius: var(--radius);
    }

    .tenant:hover,
    .tenant:focus-visible {
      border-color: var(--color-primary);
    }

    .name {
      font-weight: 600;
    }

    .meta {
      display: flex;
      gap: var(--space-2);
      align-items: center;
      font-size: 0.875rem;
      color: var(--color-text-muted);
    }
  `,
})
export class TenantSwitcherPage implements OnInit {
  protected readonly context = inject(TenantContextService);
  private readonly language = inject(LanguageService);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly errors = inject(ErrorMessageService);

  protected readonly state = signal<'loading' | 'ready' | 'error'>('loading');
  protected readonly error = signal<string | null>(null);

  ngOnInit(): void {
    void this.load(false);
  }

  protected async load(force: boolean): Promise<void> {
    this.state.set('loading');
    try {
      await this.context.ensureLoaded(force);
      this.state.set('ready');
      // One showroom: nothing to choose. (The top bar links here only when
      // there are several, so this never loops.)
      const memberships = this.context.memberships();
      if (memberships.length === 1) {
        await this.router.navigate(['/t', memberships[0].tenant_id, 'dashboard']);
      }
    } catch (error) {
      this.error.set(this.errors.message(error));
      this.state.set('error');
    }
  }

  protected name(membership: Membership): string {
    return this.language.language() === 'en' && membership.tenant_name_en
      ? membership.tenant_name_en
      : membership.tenant_name_ar;
  }

  protected open(membership: Membership): void {
    void this.router.navigate(['/t', membership.tenant_id, 'dashboard']);
  }

  protected async signOut(): Promise<void> {
    await this.auth.signOut();
    this.context.clear();
    await this.router.navigate(['/login']);
  }
}
