import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule, NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { MessageModule } from 'primeng/message';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';

import { Member, Role } from '../../../core/api/api.models';
import { AppDatePipe } from '../../../core/format/format.service';
import { LanguageService } from '../../../core/i18n/language.service';
import { TenantContextService } from '../../../core/tenant/tenant-context.service';
import { StateComponent } from '../../../shared/components/state.component';
import { ErrorMessageService } from '../../../shared/error-message.service';
import { UsersService } from './users.service';

/** Settings → Users: invite people and set their role (BACKLOG 1.9). */
@Component({
  selector: 'app-users-page',
  imports: [
    FormsModule,
    ReactiveFormsModule,
    TranslocoPipe,
    ButtonModule,
    DialogModule,
    InputTextModule,
    MessageModule,
    SelectModule,
    TableModule,
    TagModule,
    StateComponent,
    AppDatePipe,
  ],
  templateUrl: './users.page.html',
  styleUrl: './users.page.scss',
})
export class UsersPage implements OnInit {
  private readonly users = inject(UsersService);
  private readonly toast = inject(MessageService);
  private readonly errors = inject(ErrorMessageService);
  private readonly transloco = inject(TranslocoService);
  protected readonly language = inject(LanguageService);
  protected readonly context = inject(TenantContextService);

  protected readonly state = signal<'loading' | 'ready' | 'error'>('loading');
  protected readonly loadError = signal<string | null>(null);
  protected readonly members = signal<Member[]>([]);
  protected readonly roles = signal<Role[]>([]);

  protected readonly inviteOpen = signal(false);
  protected readonly inviting = signal(false);
  protected readonly inviteError = signal<string | null>(null);
  protected readonly inviteForm = inject(NonNullableFormBuilder).group({
    email: ['', [Validators.required, Validators.email]],
    full_name: [''],
    role_code: ['SALES', Validators.required],
  });

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.state.set('loading');
    try {
      const [members, roles] = await Promise.all([this.users.list(), this.users.roles()]);
      this.members.set(members);
      this.roles.set(roles);
      this.state.set('ready');
    } catch (error) {
      this.loadError.set(this.errors.message(error));
      this.state.set('error');
    }
  }

  protected roleLabel(role: Role): string {
    return this.language.language() === 'ar' ? role.name_ar : role.name_en;
  }

  protected openInvite(): void {
    this.inviteForm.reset({ email: '', full_name: '', role_code: 'SALES' });
    this.inviteError.set(null);
    this.inviteOpen.set(true);
  }

  protected async sendInvite(): Promise<void> {
    if (this.inviteForm.invalid || this.inviting()) {
      return;
    }
    this.inviting.set(true);
    this.inviteError.set(null);
    const { email, full_name, role_code } = this.inviteForm.getRawValue();
    try {
      const member = await this.users.invite({
        email: email.trim(),
        role_code,
        ...(full_name.trim() ? { full_name: full_name.trim() } : {}),
      });
      this.members.update((list) => [...list, member]);
      this.inviteOpen.set(false);
      this.toast.add({ severity: 'success', summary: email.trim(), detail: this.transloco.translate('users.invited') });
    } catch (error) {
      this.inviteError.set(this.errors.message(error));
    } finally {
      this.inviting.set(false);
    }
  }

  protected async changeRole(member: Member, roleCode: string): Promise<void> {
    await this.apply(member, { role_code: roleCode });
  }

  protected async toggleStatus(member: Member): Promise<void> {
    await this.apply(member, { status: member.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE' });
  }

  private async apply(member: Member, changes: { role_code?: string; status?: 'ACTIVE' | 'DISABLED' }): Promise<void> {
    try {
      const updated = await this.users.update(member.membership_id, changes);
      this.members.update((list) => list.map((m) => (m.membership_id === updated.membership_id ? updated : m)));
    } catch (error) {
      this.toast.add({ severity: 'error', summary: this.errors.message(error) });
      // Re-read so the row shows the real state after a refused change.
      await this.load();
    }
  }
}
