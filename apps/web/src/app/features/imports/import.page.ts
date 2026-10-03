import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';

import { ImportJob, ImportPosting } from '../../core/api/api.models';
import { FormatService } from '../../core/format/format.service';
import { LanguageService } from '../../core/i18n/language.service';
import { CanDirective } from '../../core/permissions/can.directive';
import { TenantContextService } from '../../core/tenant/tenant-context.service';
import { saveBlob } from '../../shared/download';
import { ErrorMessageService } from '../../shared/error-message.service';
import { ImportReviewComponent } from './import-review.component';
import { fileToBase64, ImportsService } from './imports.service';
import { OpeningEquityComponent } from './opening-equity.component';

/** Excel import (SPEC §4.13): upload → map → check → import with one opening entry. */
@Component({
  selector: 'app-import-page',
  imports: [
    FormsModule,
    RouterLink,
    TranslocoPipe,
    ButtonModule,
    InputTextModule,
    MessageModule,
    CanDirective,
    ImportReviewComponent,
    OpeningEquityComponent,
  ],
  template: `
    <div class="page-header">
      <h1 class="page-title">{{ 'imports.title' | transloco }}</h1>
      <p-button icon="pi pi-file-excel" [outlined]="true" [label]="'imports.template' | transloco" (onClick)="template()" />
    </div>

    @if (done(); as d) {
      <section class="card" data-testid="import-done">
        <h2><i class="pi pi-check-circle" aria-hidden="true"></i> {{ 'imports.done' | transloco }}</h2>
        <ul>
          @for (item of counts(d); track item[0]) {
            <li>{{ 'imports.count_' + item[0] | transloco: { n: item[1] } }}</li>
          }
        </ul>
        @if (d.journal_entries.length) {
          <p>{{ 'imports.entry' | transloco: { n: d.journal_entries[0].entry_no } }}</p>
        }
        <a [routerLink]="['/t', context.activeTenantId(), 'vehicles']">{{ 'menu.vehicles' | transloco }}</a>
      </section>
      <app-opening-equity *appCan="'partner.equity.change'" />
      <p-button [text]="true" icon="pi pi-plus" [label]="'imports.another' | transloco" (onClick)="reset()" />
    } @else if (job(); as j) {
      <app-import-review [job]="j" (changed)="job.set($event)" (committed)="done.set($event)" />
    } @else {
      <section class="card upload" data-testid="import-upload">
        <p class="sub">{{ 'imports.intro' | transloco }}</p>
        <div class="field">
          <label for="go-live">{{ 'imports.goLive' | transloco }}</label>
          <input pInputText id="go-live" type="date" [(ngModel)]="goLive" />
          <small class="sub">{{ 'imports.goLiveHint' | transloco }}</small>
        </div>
        <label class="file">
          <i class="pi pi-upload" aria-hidden="true"></i> {{ 'imports.chooseFile' | transloco }}
          <input type="file" accept=".xlsx,.csv" (change)="upload($event)" data-testid="import-file" hidden />
        </label>
        @if (busy()) { <p class="sub">{{ 'common.loading' | transloco }}…</p> }
        @if (error()) { <p-message severity="error" data-testid="import-error">{{ error() }}</p-message> }
      </section>
    }
  `,
  styles: `
    .upload {
      display: grid;
      gap: var(--space-3);
      max-inline-size: 560px;
    }
    .file {
      display: inline-flex;
      gap: var(--space-2);
      align-items: center;
      justify-content: center;
      padding: var(--space-4);
      font-weight: 600;
      cursor: pointer;
      border: 2px dashed var(--color-border);
      border-radius: 8px;
    }
  `,
})
export class ImportPage implements OnInit {
  private readonly api = inject(ImportsService);
  private readonly errors = inject(ErrorMessageService);
  private readonly format = inject(FormatService);
  private readonly language = inject(LanguageService);
  protected readonly context = inject(TenantContextService);

  protected readonly job = signal<ImportJob | null>(null);
  protected readonly done = signal<ImportPosting | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected goLive = '';

  ngOnInit(): void {
    this.goLive = this.format.todayIso();
  }

  protected counts(posting: ImportPosting): [string, number][] {
    return Object.entries((posting.document.result ?? {}) as Record<string, number>).filter(([, n]) => n > 0);
  }

  protected async template(): Promise<void> {
    saveBlob(await this.api.template(this.language.language()), 'sayyara-import-template.xlsx');
  }

  protected async upload(event: Event): Promise<void> {
    const file = (event.target as HTMLInputElement).files?.[0];
    (event.target as HTMLInputElement).value = '';
    if (!file) {
      return;
    }
    this.busy.set(true);
    this.error.set(null);
    try {
      this.job.set(
        await this.api.create({
          go_live_date: this.goLive,
          file_name: file.name,
          content_base64: await fileToBase64(file),
          sheets: [],
        }),
      );
    } catch (error) {
      this.error.set(this.errors.message(error));
    } finally {
      this.busy.set(false);
    }
  }

  protected reset(): void {
    this.job.set(null);
    this.done.set(null);
  }
}
