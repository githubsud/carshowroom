import { Component, inject, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { PasswordModule } from 'primeng/password';

import { AuthService } from '../../core/auth/auth.service';
import { ErrorMessageService } from '../../shared/error-message.service';

/** Self-serve signup (SPEC §4.16): an account, then the showroom on a free trial. */
@Component({
  selector: 'app-signup-page',
  imports: [ReactiveFormsModule, RouterLink, TranslocoPipe, ButtonModule, InputTextModule, PasswordModule, MessageModule],
  template: `
    <div class="card">
      <h1>{{ 'signup.title' | transloco }}</h1>
      <p class="subtitle">{{ 'signup.subtitle' | transloco }}</p>
      <form [formGroup]="form" (ngSubmit)="submit()" data-testid="signup-form">
        <div class="field">
          <label for="su-name">{{ 'signup.name' | transloco }}</label>
          <input pInputText id="su-name" formControlName="name" autocomplete="name" data-testid="su-name" />
        </div>
        <div class="field">
          <label for="su-email">{{ 'auth.email' | transloco }}</label>
          <input pInputText id="su-email" type="email" formControlName="email" autocomplete="username" dir="ltr"
                 data-testid="su-email" />
        </div>
        <div class="field">
          <label for="su-password">{{ 'auth.password' | transloco }}</label>
          <p-password inputId="su-password" formControlName="password" [toggleMask]="true" [feedback]="false"
                      autocomplete="new-password" [fluid]="true" />
          <small class="hint">{{ 'signup.passwordHint' | transloco }}</small>
        </div>
        @if (error()) { <p-message severity="error" data-testid="signup-error">{{ error() }}</p-message> }
        <p-button type="submit" [label]="'signup.create' | transloco" [loading]="busy()" [disabled]="form.invalid"
                  data-testid="signup-submit" />
      </form>
      <div class="links"><a routerLink="/login">{{ 'signup.haveAccount' | transloco }}</a></div>
    </div>
  `,
  styleUrl: './auth-layout.scss',
})
export class SignupPage {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly errors = inject(ErrorMessageService);

  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly form = inject(NonNullableFormBuilder).group({
    name: ['', Validators.required],
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(10)]],
  });

  protected async submit(): Promise<void> {
    if (this.form.invalid) {
      return;
    }
    this.busy.set(true);
    this.error.set(null);
    try {
      const v = this.form.getRawValue();
      await this.auth.signUp(v.email.trim(), v.password, v.name.trim());
      await this.router.navigate(['/create-showroom']);
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }
}
