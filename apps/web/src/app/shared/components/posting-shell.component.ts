import { Component, input, output } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { MessageModule } from 'primeng/message';

import { Preview } from '../../core/api/api.models';
import { PostingPreviewComponent } from './posting-preview.component';

/**
 * Frame of a money dialog (SPEC §9.3): the fields (projected), then the
 * plain-language preview, then confirm. The logic lives in PostingDialogBase.
 */
@Component({
  selector: 'app-posting-shell',
  imports: [ReactiveFormsModule, TranslocoPipe, ButtonModule, DialogModule, MessageModule, PostingPreviewComponent],
  template: `
    <p-dialog [visible]="visible()" (visibleChange)="dismiss.emit()" [modal]="true" [header]="header()"
              [style]="{ width: 'min(520px, 96vw)' }" [dismissableMask]="!busy()">
      @if (step() === 'form') {
        <form class="dialog-form" [formGroup]="form()" (ngSubmit)="review.emit()" [attr.data-testid]="testId()">
          <ng-content />
          @if (error()) {
            <p-message severity="error" data-testid="dialog-error">{{ error() }}</p-message>
          }
          <div class="actions">
            <p-button type="button" [text]="true" [label]="'common.cancel' | transloco" (onClick)="dismiss.emit()" />
            <p-button type="submit" data-testid="review" [label]="'finance.review' | transloco" [loading]="busy()" />
          </div>
        </form>
      } @else {
        @if (preview(); as p) {
          <app-posting-preview [preview]="p" />
        }
        @if (error()) {
          <p-message severity="error" data-testid="dialog-error">{{ error() }}</p-message>
        }
        <div class="actions">
          <p-button type="button" [text]="true" icon="pi pi-arrow-right" [label]="'finance.back' | transloco"
                    (onClick)="back.emit()" [disabled]="busy()" />
          <p-button type="button" data-testid="confirm" icon="pi pi-check" [label]="'finance.confirm' | transloco"
                    [loading]="busy()" (onClick)="confirm.emit()" />
        </div>
      }
    </p-dialog>
  `,
  styles: `
    .dialog-form {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }
    .actions {
      display: flex;
      gap: var(--space-2);
      justify-content: flex-end;
      margin-block-start: var(--space-3);
    }
  `,
})
export class PostingShellComponent {
  readonly visible = input.required<boolean>();
  readonly header = input.required<string>();
  readonly form = input.required<FormGroup>();
  readonly step = input.required<'form' | 'preview'>();
  readonly preview = input<Preview | null>(null);
  readonly error = input<string | null>(null);
  readonly busy = input(false);
  readonly testId = input('posting-form');

  readonly review = output();
  readonly confirm = output();
  readonly back = output();
  readonly dismiss = output();
}
