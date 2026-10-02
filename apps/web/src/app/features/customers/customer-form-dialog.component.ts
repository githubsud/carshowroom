import { Component, effect, inject, input, model, output, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';

import { ApiError, Customer } from '../../core/api/api.models';
import { ErrorMessageService } from '../../shared/error-message.service';
import { CustomersService } from './customers.service';

/**
 * Add a customer with the fewest fields possible: name and phone (SPEC §4.6).
 * A phone that already exists offers the existing customer instead.
 */
@Component({
  selector: 'app-customer-form-dialog',
  imports: [ReactiveFormsModule, TranslocoPipe, ButtonModule, CheckboxModule, DialogModule, InputTextModule, MessageModule],
  template: `
    <p-dialog [visible]="visible()" (visibleChange)="visible.set($event)" [modal]="true"
              [header]="'customers.add' | transloco" [style]="{ width: 'min(440px, 96vw)' }">
      <form class="dialog-form" [formGroup]="form" (ngSubmit)="save()" data-testid="customer-form">
        <div class="field">
          <label for="c-name">{{ 'customers.name' | transloco }}</label>
          <input pInputText id="c-name" formControlName="name" data-testid="customer-name" />
        </div>
        <div class="field">
          <label for="c-phone">{{ 'customers.phone' | transloco }}</label>
          <input pInputText id="c-phone" formControlName="phone" inputmode="tel" dir="ltr" data-testid="customer-phone" />
        </div>
        <div class="field">
          <label for="c-nid">{{ 'customers.nationalId' | transloco }}</label>
          <input pInputText id="c-nid" formControlName="national_id" dir="ltr" />
        </div>
        @if (error()) {
          <p-message severity="error" data-testid="dialog-error">{{ error() }}</p-message>
        }
        @if (existing(); as e) {
          <p-button type="button" [outlined]="true" icon="pi pi-user" data-testid="use-existing"
                    [label]="('customers.useExisting' | transloco) + ': ' + e.name" (onClick)="useExisting()" />
        }
        <div class="actions">
          <p-button type="button" [text]="true" [label]="'common.cancel' | transloco" (onClick)="visible.set(false)" />
          <p-button type="submit" [label]="'settings.save' | transloco" [loading]="busy()" data-testid="customer-save" />
        </div>
      </form>
    </p-dialog>
  `,
  styleUrl: '../finance/posting-dialog.scss',
})
export class CustomerFormDialogComponent {
  private readonly api = inject(CustomersService);
  private readonly errors = inject(ErrorMessageService);

  readonly visible = model(false);
  readonly initialName = input('');
  readonly saved = output<Customer>();

  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly existing = signal<{ id: string; name: string } | null>(null);
  protected readonly form = inject(NonNullableFormBuilder).group({
    name: ['', Validators.required],
    phone: [''],
    national_id: ['', Validators.pattern(/^[0-9A-Za-z]{4,20}$/)],
  });

  constructor() {
    effect(() => {
      if (this.visible()) {
        this.form.reset({ name: this.initialName(), phone: '', national_id: '' });
        this.error.set(null);
        this.existing.set(null);
      }
    });
  }

  protected async save(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const v = this.form.getRawValue();
    this.busy.set(true);
    this.error.set(null);
    this.existing.set(null);
    try {
      const customer = await this.api.create({
        name: v.name.trim(),
        phone: v.phone.trim() || null,
        national_id: v.national_id.trim() || null,
        is_buyer: false,
        is_seller: false,
      });
      this.visible.set(false);
      this.saved.emit(customer);
    } catch (error) {
      this.error.set(this.errors.message(error));
      if (error instanceof ApiError && error.code === 'CUSTOMER_PHONE_EXISTS') {
        this.existing.set({ id: String(error.details['customer_id']), name: String(error.details['name']) });
      }
    } finally {
      this.busy.set(false);
    }
  }

  protected async useExisting(): Promise<void> {
    const existing = this.existing();
    if (!existing) {
      return;
    }
    const detail = await this.api.get(existing.id);
    this.visible.set(false);
    this.saved.emit(detail.customer);
  }
}
