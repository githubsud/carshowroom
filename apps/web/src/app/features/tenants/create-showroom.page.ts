import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';

import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { ErrorMessageService } from '../../shared/error-message.service';
import { PlatformService } from '../admin/platform.service';

/** Create a showroom on the trial plan (SPEC §4.16), then onboarding. */
@Component({
  selector: 'app-create-showroom-page',
  imports: [FormsModule, TranslocoPipe, ButtonModule, InputTextModule, MessageModule],
  template: `
    <div class="card">
      <h1>{{ 'signup.showroomTitle' | transloco }}</h1>
      <p class="subtitle">{{ 'signup.trial' | transloco }}</p>
      <div class="field">
        <label for="cs-name">{{ 'onboarding.nameAr' | transloco }}</label>
        <input pInputText id="cs-name" [(ngModel)]="nameAr" data-testid="cs-name" />
      </div>
      <div class="field">
        <label for="cs-name-en">{{ 'onboarding.nameEn' | transloco }}</label>
        <input pInputText id="cs-name-en" [(ngModel)]="nameEn" dir="ltr" />
      </div>
      <div class="field">
        <label for="cs-country">{{ 'signup.country' | transloco }}</label>
        <select id="cs-country" [(ngModel)]="country">
          <option value="EG">{{ 'signup.country_EG' | transloco }}</option>
          <option value="QA">{{ 'signup.country_QA' | transloco }}</option>
        </select>
      </div>
      @if (error()) { <p-message severity="error">{{ error() }}</p-message> }
      <p-button [label]="'signup.createShowroom' | transloco" (onClick)="create()" [loading]="busy()"
                [disabled]="!nameAr.trim()" data-testid="cs-create" />
    </div>
  `,
  styleUrl: '../auth/auth-layout.scss',
})
export class CreateShowroomPage {
  private readonly api = inject(PlatformService);
  private readonly context = inject(TenantContextService);
  private readonly router = inject(Router);
  private readonly errors = inject(ErrorMessageService);

  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected nameAr = '';
  protected nameEn = '';
  protected country: 'EG' | 'QA' = 'EG';

  protected async create(): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      const { tenant_id } = await this.api.signup({
        name_ar: this.nameAr.trim(),
        name_en: this.nameEn.trim() || null,
        country_code: this.country,
      });
      await this.context.ensureLoaded(true);
      await this.router.navigate(['/t', tenant_id, 'onboarding']);
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }
}
