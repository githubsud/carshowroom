import { Component, forwardRef, inject, input, signal } from '@angular/core';
import { ControlValueAccessor, FormsModule, NG_VALUE_ACCESSOR } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { AutoCompleteCompleteEvent, AutoCompleteModule, AutoCompleteSelectEvent } from 'primeng/autocomplete';
import { ButtonModule } from 'primeng/button';

import { Customer } from '../../core/api/api.models';
import { CustomerFormDialogComponent } from './customer-form-dialog.component';
import { CustomersService } from './customers.service';

interface Pick {
  id: string;
  label: string;
}

/**
 * Choose a customer by typing a name or the first digits of a phone number;
 * "+" adds a new one without leaving the form. The control value is the id.
 */
@Component({
  selector: 'app-customer-picker',
  imports: [FormsModule, TranslocoPipe, AutoCompleteModule, ButtonModule, CustomerFormDialogComponent],
  providers: [{ provide: NG_VALUE_ACCESSOR, useExisting: forwardRef(() => CustomerPickerComponent), multi: true }],
  template: `
    <div class="picker">
      <p-autocomplete
        [inputId]="inputId()"
        [ngModel]="selected()"
        [ngModelOptions]="{ standalone: true }"
        (ngModelChange)="typed($event)"
        [suggestions]="results()"
        (completeMethod)="search($event)"
        (onSelect)="choose($event)"
        optionLabel="label"
        [forceSelection]="true"
        [minQueryLength]="2"
        [delay]="250"
        [fluid]="true"
        [disabled]="disabled()"
        [placeholder]="'customers.searchHint' | transloco"
        [attr.data-testid]="testId()"
      />
      <p-button type="button" icon="pi pi-user-plus" [outlined]="true" [disabled]="disabled()"
                [ariaLabel]="'customers.add' | transloco" (onClick)="adding.set(true)"
                [attr.data-testid]="testId() + '-add'" />
    </div>
    <app-customer-form-dialog [(visible)]="adding" [initialName]="lastQuery()" (saved)="created($event)" />
  `,
  styles: `
    .picker {
      display: flex;
      gap: var(--space-2);
      align-items: center;
    }
    p-autocomplete {
      flex: 1;
    }
  `,
})
export class CustomerPickerComponent implements ControlValueAccessor {
  private readonly api = inject(CustomersService);

  readonly inputId = input('customer');
  readonly testId = input('customer-picker');

  protected readonly selected = signal<Pick | null>(null);
  protected readonly results = signal<Pick[]>([]);
  protected readonly adding = signal(false);
  protected readonly lastQuery = signal('');
  protected readonly disabled = signal(false);
  private onChange: (value: string) => void = () => undefined;
  private onTouched: () => void = () => undefined;

  /** Pre-fill a label for a known id (e.g. an existing draft). */
  setLabel(customer: { id: string; name: string } | null): void {
    this.selected.set(customer ? { id: customer.id, label: customer.name } : null);
  }

  writeValue(value: string | null): void {
    if (!value) {
      this.selected.set(null);
    } else if (this.selected()?.id !== value) {
      void this.api.get(value).then((d) => this.selected.set({ id: d.customer.id, label: this.label(d.customer) }));
    }
  }

  registerOnChange(fn: (value: string) => void): void {
    this.onChange = fn;
  }

  registerOnTouched(fn: () => void): void {
    this.onTouched = fn;
  }

  setDisabledState(disabled: boolean): void {
    this.disabled.set(disabled);
  }

  protected async search(event: AutoCompleteCompleteEvent): Promise<void> {
    this.lastQuery.set(event.query);
    const page = await this.api.list({ q: event.query, page_size: 8 });
    this.results.set(page.items.map((c) => ({ id: c.id, label: this.label(c) })));
  }

  protected typed(value: Pick | string | null): void {
    if (value === null || typeof value === 'string') {
      this.selected.set(null);
      this.onChange('');
    }
  }

  protected choose(event: AutoCompleteSelectEvent): void {
    const pick = event.value as Pick;
    this.selected.set(pick);
    this.onChange(pick.id);
    this.onTouched();
  }

  protected created(customer: Customer): void {
    const pick = { id: customer.id, label: this.label(customer) };
    this.selected.set(pick);
    this.onChange(pick.id);
    this.onTouched();
  }

  private label(customer: Customer): string {
    return customer.phone_primary ? `${customer.name} — ${customer.phone_primary}` : customer.name;
  }
}
