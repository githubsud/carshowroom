import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeUrl } from '@angular/platform-browser';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';

import { AuthService } from '../../core/auth/auth.service';
import { ErrorMessageService } from '../../shared/error-message.service';

/** Account security (BACKLOG 9.8): two-step sign-in with an authenticator app (TOTP). */
@Component({
  selector: 'app-account-page',
  imports: [FormsModule, TranslocoPipe, ButtonModule, InputTextModule, MessageModule],
  template: `
    <div class="page-header"><h1 class="page-title">{{ 'account.title' | transloco }}</h1></div>
    <section class="card" data-testid="mfa">
      <h2>{{ 'account.mfa' | transloco }}</h2>
      <p class="sub">{{ 'account.mfaHint' | transloco }}</p>
      @if (verified(); as factorId) {
        <p class="on"><i class="pi pi-shield" aria-hidden="true"></i> {{ 'account.mfaOn' | transloco }}</p>
        <p-button severity="danger" [outlined]="true" [label]="'account.mfaOff' | transloco" (onClick)="disable(factorId)" />
      } @else if (enrolling(); as e) {
        <p>{{ 'account.scan' | transloco }}</p>
        <img [src]="e.qr" alt="" width="180" height="180" />
        <p class="secret" dir="ltr">{{ e.secret }}</p>
        <div class="row">
          <input pInputText [(ngModel)]="code" inputmode="numeric" maxlength="6" dir="ltr"
                 [attr.aria-label]="'auth.mfaCode' | transloco" />
          <p-button [label]="'auth.verify' | transloco" (onClick)="confirm(e.factorId)" [disabled]="code.length < 6" />
        </div>
      } @else {
        <p-button icon="pi pi-qrcode" [label]="'account.mfaStart' | transloco" (onClick)="start()" data-testid="mfa-start" />
      }
      @if (error()) { <p-message severity="error">{{ error() }}</p-message> }
    </section>
  `,
  styles: `
    .row {
      display: flex;
      gap: var(--space-2);
    }
    .secret {
      font-family: monospace;
      overflow-wrap: anywhere;
    }
    .on {
      font-weight: 600;
      color: #166534;
    }
  `,
})
export class AccountPage implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly errors = inject(ErrorMessageService);
  private readonly sanitizer = inject(DomSanitizer);

  protected readonly verified = signal<string | null>(null);
  protected readonly enrolling = signal<{ factorId: string; qr: SafeUrl; secret: string } | null>(null);
  protected readonly error = signal<string | null>(null);
  protected code = '';

  async ngOnInit(): Promise<void> {
    await this.refresh();
  }

  private async refresh(): Promise<void> {
    try {
      const factors = await this.auth.factors();
      this.verified.set(factors.find((f) => f.status === 'verified')?.id ?? null);
    } catch (error) {
      this.error.set(this.errors.message(error));
    }
  }

  protected async start(): Promise<void> {
    try {
      // Unfinished enrolments block a new one; clear them first.
      for (const f of await this.auth.factors()) {
        if (f.status !== 'verified') {
          await this.auth.unenroll(f.id);
        }
      }
      const e = await this.auth.enroll();
      this.enrolling.set({ factorId: e.factorId, qr: this.sanitizer.bypassSecurityTrustUrl(e.qr), secret: e.secret });
    } catch (error) {
      this.error.set(this.errors.message(error));
    }
  }

  protected async confirm(factorId: string): Promise<void> {
    try {
      await this.auth.confirmEnroll(factorId, this.code.trim());
      this.enrolling.set(null);
      this.code = '';
      await this.refresh();
    } catch (error) {
      this.error.set(this.errors.message(error));
    }
  }

  protected async disable(factorId: string): Promise<void> {
    try {
      await this.auth.unenroll(factorId);
      await this.refresh();
    } catch (error) {
      this.error.set(this.errors.message(error));
    }
  }
}
