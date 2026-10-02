import { Component, inject, signal } from '@angular/core';
import { AbstractControl, NonNullableFormBuilder, ReactiveFormsModule, ValidationErrors, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { MessageModule } from 'primeng/message';
import { PasswordModule } from 'primeng/password';

import { AuthService } from '../../core/auth/auth.service';
import { ErrorMessageService } from '../../shared/error-message.service';

/** Matches supabase/config.toml: ≥ 10 characters with lower, upper and digits. */
export function strongPassword(control: AbstractControl<string>): ValidationErrors | null {
  const value = control.value ?? '';
  const ok = value.length >= 10 && /[a-z]/.test(value) && /[A-Z]/.test(value) && /\d/.test(value);
  return ok ? null : { weakPassword: true };
}

/**
 * Landing page of invitation and password-recovery emails: supabase-js picks
 * up the session from the link, the user chooses a password.
 */
@Component({
  selector: 'app-reset-password-page',
  imports: [ReactiveFormsModule, RouterLink, TranslocoPipe, ButtonModule, PasswordModule, MessageModule],
  template: `
    <div class="card">
      <h1>{{ 'auth.setPasswordTitle' | transloco }}</h1>

      @if (!auth.isSignedIn()) {
        <p-message severity="warn">{{ 'auth.linkInvalid' | transloco }}</p-message>
        <div class="links">
          <a routerLink="/forgot-password">{{ 'auth.forgotPassword' | transloco }}</a>
        </div>
      } @else {
        <p class="subtitle">{{ 'auth.passwordRules' | transloco }}</p>
        <form [formGroup]="form" (ngSubmit)="submit()">
          <div class="field">
            <label for="password">{{ 'auth.newPassword' | transloco }}</label>
            <p-password inputId="password" formControlName="password" [toggleMask]="true" [feedback]="false" [fluid]="true" />
          </div>
          @if (error()) {
            <p-message severity="error">{{ error() }}</p-message>
          }
          <p-button
            type="submit"
            [label]="'auth.savePassword' | transloco"
            [loading]="busy()"
            [disabled]="form.invalid"
           />
        </form>
      }
    </div>
  `,
  styleUrl: './auth-layout.scss',
})
export class ResetPasswordPage {
  protected readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly errors = inject(ErrorMessageService);

  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly form = inject(NonNullableFormBuilder).group({
    password: ['', [Validators.required, strongPassword]],
  });

  protected async submit(): Promise<void> {
    if (this.form.invalid) {
      return;
    }
    this.busy.set(true);
    this.error.set(null);
    try {
      await this.auth.updatePassword(this.form.getRawValue().password);
      await this.router.navigate(['/tenants']);
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }
}
