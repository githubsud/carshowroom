import { Component, inject, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';

import { AuthService } from '../../core/auth/auth.service';
import { ErrorMessageService } from '../../shared/error-message.service';

@Component({
  selector: 'app-forgot-password-page',
  imports: [ReactiveFormsModule, RouterLink, TranslocoPipe, ButtonModule, InputTextModule, MessageModule],
  template: `
    <div class="card">
      <h1>{{ 'auth.forgotTitle' | transloco }}</h1>
      <p class="subtitle">{{ 'auth.forgotSubtitle' | transloco }}</p>

      @if (sent()) {
        <p-message severity="success">{{ 'auth.resetSent' | transloco }}</p-message>
      } @else {
        <form [formGroup]="form" (ngSubmit)="submit()">
          <div class="field">
            <label for="email">{{ 'auth.email' | transloco }}</label>
            <input pInputText id="email" type="email" formControlName="email" autocomplete="username" dir="ltr" />
          </div>
          @if (error()) {
            <p-message severity="error">{{ error() }}</p-message>
          }
          <p-button
            type="submit"
            [label]="'auth.sendResetLink' | transloco"
            [loading]="busy()"
            [disabled]="form.invalid"
           />
        </form>
      }

      <div class="links">
        <a routerLink="/login">{{ 'auth.backToLogin' | transloco }}</a>
      </div>
    </div>
  `,
  styleUrl: './auth-layout.scss',
})
export class ForgotPasswordPage {
  private readonly auth = inject(AuthService);
  private readonly errors = inject(ErrorMessageService);

  protected readonly busy = signal(false);
  protected readonly sent = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly form = inject(NonNullableFormBuilder).group({
    email: ['', [Validators.required, Validators.email]],
  });

  protected async submit(): Promise<void> {
    if (this.form.invalid) {
      return;
    }
    this.busy.set(true);
    this.error.set(null);
    try {
      await this.auth.sendPasswordReset(
        this.form.getRawValue().email.trim(),
        `${window.location.origin}/reset-password`,
      );
      // Same answer whether or not the email exists.
      this.sent.set(true);
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }
}
