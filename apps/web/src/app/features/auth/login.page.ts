import { Component, inject, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { PasswordModule } from 'primeng/password';

import { AuthService } from '../../core/auth/auth.service';
import { PRODUCT_NAME, PRODUCT_NAME_AR } from '../../core/config/product';
import { LanguageService } from '../../core/i18n/language.service';
import { ErrorMessageService } from '../../shared/error-message.service';

@Component({
  selector: 'app-login-page',
  imports: [ReactiveFormsModule, RouterLink, TranslocoPipe, ButtonModule, InputTextModule, PasswordModule, MessageModule],
  template: `
    <div class="card">
      <div class="header">
        <h1>{{ language.language() === 'ar' ? productNameAr : productName }}</h1>
        <p-button
          type="button"
          [text]="true"
          data-testid="language-toggle"
          [label]="'shell.switchLanguage' | transloco"
          (onClick)="language.toggle()"
         />
      </div>
      <p class="subtitle">{{ 'auth.loginSubtitle' | transloco }}</p>

      <form [formGroup]="form" (ngSubmit)="submit()">
        <div class="field">
          <label for="email">{{ 'auth.email' | transloco }}</label>
          <input pInputText id="email" type="email" formControlName="email" autocomplete="username" dir="ltr" />
        </div>
        <div class="field">
          <label for="password">{{ 'auth.password' | transloco }}</label>
          <p-password
            inputId="password"
            formControlName="password"
            [feedback]="false"
            [toggleMask]="true"
            autocomplete="current-password"
            [fluid]="true"
          />
        </div>

        @if (error()) {
          <p-message severity="error" data-testid="login-error">{{ error() }}</p-message>
        }

        <p-button
          type="submit"
          data-testid="login-submit"
          [label]="'auth.signIn' | transloco"
          [loading]="busy()"
          [disabled]="form.invalid"
         />
      </form>

      <div class="links">
        <a routerLink="/forgot-password">{{ 'auth.forgotPassword' | transloco }}</a>
      </div>
    </div>
  `,
  styleUrl: './auth-layout.scss',
})
export class LoginPage {
  protected readonly language = inject(LanguageService);
  protected readonly productName = PRODUCT_NAME;
  protected readonly productNameAr = PRODUCT_NAME_AR;
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly errors = inject(ErrorMessageService);

  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly form = inject(NonNullableFormBuilder).group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', Validators.required],
  });

  protected async submit(): Promise<void> {
    if (this.form.invalid || this.busy()) {
      return;
    }
    this.busy.set(true);
    this.error.set(null);
    try {
      const { email, password } = this.form.getRawValue();
      await this.auth.signIn(email.trim(), password);
      const returnUrl = this.route.snapshot.queryParamMap.get('returnUrl');
      await this.router.navigateByUrl(returnUrl?.startsWith('/') ? returnUrl : '/tenants');
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }
}
