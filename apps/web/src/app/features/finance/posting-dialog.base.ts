import { computed, Directive, effect, inject, input, model, signal } from '@angular/core';
import { FormGroup } from '@angular/forms';

import { CashAccount, Partner, Preview } from '../../core/api/api.models';
import { FormatService } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { ErrorMessageService } from '../../shared/error-message.service';

export type PostingKind =
  | 'expense'
  | 'transfer'
  | 'income'
  | 'partner'
  | 'vehicleExpense'
  | 'purchase'
  | 'sellerPayment'
  | 'reservation'
  | 'settle'
  | 'supplierPayment'
  | 'refund'
  | 'cancelSale'
  | 'receipt'
  | 'paperAction'
  | 'consignment'
  | 'externalSale';

export interface Option {
  value: string;
  label: string;
}

/**
 * Shared flow of every money dialog (SPEC §9.3): form → plain-language preview
 * → confirm. One Idempotency-Key per opening, so a double tap or a retry after
 * a dropped connection posts once (BR-L12).
 */
@Directive()
export abstract class PostingDialogBase<TBody, TResult> {
  protected readonly format = inject(FormatService);
  protected readonly language = inject(LanguageService);
  private readonly errors = inject(ErrorMessageService);

  readonly visible = model(false);
  readonly accounts = input<CashAccount[]>([]);
  readonly partners = input<Partner[]>([]);

  abstract readonly kind: PostingKind;
  abstract readonly form: FormGroup;
  abstract readonly dateControl: string;
  abstract readonly noteControl: string;

  protected readonly step = signal<'form' | 'preview'>('form');
  protected readonly preview = signal<Preview | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  private idempotencyKey = crypto.randomUUID();

  protected readonly accountOptions = computed<Option[]>(() =>
    this.accounts().map((a) => ({ value: a.id, label: this.name(a) })),
  );
  protected readonly partnerOptions = computed<Option[]>(() =>
    this.partners().map((p) => ({ value: p.id, label: this.name(p) })),
  );

  // Expense-only (rule 30); the other dialogs keep the defaults.
  protected readonly funding = signal<'cash' | 'partner'>('cash');
  protected readonly fundingOptions = computed<Option[]>(() => []);
  protected readonly modeOptions = computed<Option[]>(() => []);
  protected readonly categoryOptions = computed<Option[]>(() => []);
  protected setFunding(value: 'cash' | 'partner'): void {
    this.funding.set(value);
  }

  constructor() {
    effect(() => {
      if (this.visible()) {
        this.idempotencyKey = crypto.randomUUID();
        this.step.set('form');
        this.preview.set(null);
        this.error.set(null);
        this.funding.set('cash');
        this.reset();
      }
    });
  }

  /** Put the form back to its smart defaults (today, default cash box...). */
  protected abstract reset(): void;
  protected abstract body(): TBody;
  protected abstract previewCall(body: TBody): Promise<Preview>;
  protected abstract postCall(body: TBody, idempotencyKey: string): Promise<TResult>;
  protected abstract emitPosted(result: TResult): void;

  protected name(item: { name_ar: string; name_en?: string | null }): string {
    return this.language.language() === 'ar' ? item.name_ar : (item.name_en ?? item.name_ar);
  }

  protected defaultAccountId(): string {
    return this.accounts().find((a) => a.is_default)?.id ?? this.accounts()[0]?.id ?? '';
  }

  protected async review(): Promise<void> {
    if (this.form.invalid || this.busy()) {
      this.form.markAllAsTouched();
      return;
    }
    await this.run(async () => {
      this.preview.set(await this.previewCall(this.body()));
      this.step.set('preview');
    });
  }

  protected async confirm(): Promise<void> {
    await this.run(async () => {
      const result = await this.postCall(this.body(), this.idempotencyKey);
      this.visible.set(false);
      this.emitPosted(result);
    });
  }

  protected back(): void {
    this.step.set('form');
    this.error.set(null);
  }

  private async run(action: () => Promise<void>): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      await action();
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }
}
