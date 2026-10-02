import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { TextareaModule } from 'primeng/textarea';

import { JournalEntry, Preview } from '../../core/api/api.models';
import { AppDatePipe, MoneyPipe } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { PostingPreviewComponent } from '../../shared/components/posting-preview.component';
import { StateComponent } from '../../shared/components/state.component';
import { ErrorMessageService } from '../../shared/error-message.service';
import { FinanceService } from './finance.service';

const PAGE_SIZE = 25;

/**
 * General journal for accountants (journal.view): numbered entries, their
 * debit/credit lines, and reversal with a mandatory reason (SPEC §4.11).
 */
@Component({
  selector: 'app-journal-page',
  imports: [
    FormsModule,
    TranslocoPipe,
    ButtonModule,
    DialogModule,
    InputTextModule,
    MessageModule,
    TableModule,
    TagModule,
    TextareaModule,
    AppDatePipe,
    MoneyPipe,
    CanDirective,
    StateComponent,
    PostingPreviewComponent,
  ],
  templateUrl: './journal.page.html',
  styleUrl: './journal.page.scss',
})
/** The lazy table requests the first page itself (onLazyLoad), so there is no ngOnInit load. */
export class JournalPage {
  private readonly finance = inject(FinanceService);
  private readonly toast = inject(MessageService);
  private readonly transloco = inject(TranslocoService);
  private readonly errors = inject(ErrorMessageService);
  protected readonly language = inject(LanguageService);

  protected readonly entries = signal<JournalEntry[]>([]);
  protected readonly total = signal(0);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected entryNo = '';
  protected first = 0;

  protected readonly detail = signal<JournalEntry | null>(null);
  protected readonly detailOpen = signal(false);

  protected readonly reverseStep = signal<'reason' | 'preview' | null>(null);
  protected readonly reversePreview = signal<Preview | null>(null);
  protected readonly reverseBusy = signal(false);
  protected readonly reverseError = signal<string | null>(null);
  protected reason = '';
  private idempotencyKey = '';

  protected async load(first: number): Promise<void> {
    this.first = first;
    this.loading.set(true);
    this.loadError.set(null);
    try {
      const page = await this.finance.journalEntries({
        page: Math.floor(first / PAGE_SIZE) + 1,
        page_size: PAGE_SIZE,
        entry_no: this.entryNo.trim() || null,
      });
      this.entries.set(page.items);
      this.total.set(page.total);
    } catch (error) {
      this.loadError.set(this.errors.message(error));
    } finally {
      this.loading.set(false);
    }
  }

  protected pageSize = PAGE_SIZE;

  protected async open(entry: JournalEntry): Promise<void> {
    try {
      this.detail.set(await this.finance.journalEntry(entry.id));
      this.reverseStep.set(null);
      this.detailOpen.set(true);
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
    }
  }

  protected canReverse(entry: JournalEntry): boolean {
    return entry.reversed_by_entry_no === null && entry.reversal_of_entry_no === null;
  }

  protected startReverse(): void {
    this.reason = '';
    this.idempotencyKey = crypto.randomUUID();
    this.reverseError.set(null);
    this.reverseStep.set('reason');
  }

  protected async previewReverse(): Promise<void> {
    const entry = this.detail();
    if (!entry || this.reason.trim().length < 3) {
      return;
    }
    await this.runReverse(async () => {
      this.reversePreview.set(await this.finance.previewReverse(entry.id, { reason: this.reason.trim() }));
      this.reverseStep.set('preview');
    });
  }

  protected async confirmReverse(): Promise<void> {
    const entry = this.detail();
    if (!entry) {
      return;
    }
    await this.runReverse(async () => {
      const result = await this.finance.reverse(entry.id, { reason: this.reason.trim() }, this.idempotencyKey);
      this.toast.add({
        severity: 'success',
        summary: this.transloco.translate('journal.reversed', {
          original: result.original_entry_no,
          reversal: result.reversal.entry_no,
        }),
      });
      this.detailOpen.set(false);
      await this.load(this.first);
    });
  }

  private async runReverse(action: () => Promise<void>): Promise<void> {
    this.reverseBusy.set(true);
    this.reverseError.set(null);
    try {
      await action();
    } catch (error) {
      this.reverseError.set(this.errors.message(error));
    } finally {
      this.reverseBusy.set(false);
    }
  }
}
