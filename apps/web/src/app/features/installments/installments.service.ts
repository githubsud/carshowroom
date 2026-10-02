import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  Installment,
  InstallmentBoard,
  InstallmentKpis,
  InstallmentPlan,
  InstallmentPlanInput,
  InstallmentStatement,
  NotificationPage,
  Paper,
  PaperActionInput,
  PaperInput,
  PaperPosting,
  PlanPosting,
  Preview,
  ReceiptInput,
  ScheduleRow,
} from '../../core/api/api.models';
import { idempotent, toParams } from '../../shared/http-params';

export type BoardView = 'open' | 'due_today' | 'upcoming' | 'overdue';

/** Calls to the installment, deferred paper and notification endpoints (docs/API.md §3.7). */
@Injectable({ providedIn: 'root' })
export class InstallmentsService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  schedulePreview(financed: string, plan: InstallmentPlanInput): Promise<ScheduleRow[]> {
    return firstValueFrom(
      this.http.post<ScheduleRow[]>(`${this.base}/installment-plans/schedule-preview`, { financed, plan }),
    );
  }

  board(view: BoardView, days = 7): Promise<InstallmentBoard> {
    return firstValueFrom(this.http.get<InstallmentBoard>(`${this.base}/installments/board`, { params: toParams({ view, days }) }));
  }

  calendar(dateFrom: string, dateTo: string): Promise<Installment[]> {
    return firstValueFrom(
      this.http.get<Installment[]>(`${this.base}/installments`, {
        params: toParams({ view: 'calendar', date_from: dateFrom, date_to: dateTo }),
      }),
    );
  }

  kpis(): Promise<InstallmentKpis> {
    return firstValueFrom(this.http.get<InstallmentKpis>(`${this.base}/installments/kpis`));
  }

  plan(id: string): Promise<InstallmentPlan> {
    return firstValueFrom(this.http.get<InstallmentPlan>(`${this.base}/installment-plans/${id}`));
  }

  previewReceipt(planId: string, body: ReceiptInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/installment-plans/${planId}/receipts/preview`, body));
  }

  recordReceipt(planId: string, body: ReceiptInput, key: string): Promise<PlanPosting> {
    return firstValueFrom(
      this.http.post<PlanPosting>(`${this.base}/installment-plans/${planId}/receipts`, body, idempotent(key)),
    );
  }

  statement(customerId: string): Promise<InstallmentStatement> {
    return firstValueFrom(this.http.get<InstallmentStatement>(`${this.base}/customers/${customerId}/installment-statement`));
  }

  statementPdf(customerId: string, lang: 'ar' | 'en'): Promise<Blob> {
    return firstValueFrom(
      this.http.get(`${this.base}/customers/${customerId}/installment-statement`, {
        params: toParams({ format: 'pdf', lang }),
        responseType: 'blob',
      }),
    );
  }

  // --- Deferred papers ---------------------------------------------------------------
  papers(query: { status?: string | null; paper_type?: string | null; overdue?: boolean; customer_id?: string }): Promise<Paper[]> {
    return firstValueFrom(this.http.get<Paper[]>(`${this.base}/deferred-papers`, { params: toParams(query) }));
  }

  paper(id: string): Promise<Paper> {
    return firstValueFrom(this.http.get<Paper>(`${this.base}/deferred-papers/${id}`));
  }

  createPaper(body: PaperInput): Promise<Paper> {
    return firstValueFrom(this.http.post<Paper>(`${this.base}/deferred-papers`, body));
  }

  previewPaperAction(id: string, body: PaperActionInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/deferred-papers/${id}/actions/preview`, body));
  }

  paperAction(id: string, body: PaperActionInput, key: string): Promise<PaperPosting> {
    return firstValueFrom(this.http.post<PaperPosting>(`${this.base}/deferred-papers/${id}/actions`, body, idempotent(key)));
  }

  // --- Notifications -------------------------------------------------------------------
  notifications(unreadOnly = false): Promise<NotificationPage> {
    return firstValueFrom(
      this.http.get<NotificationPage>(`${this.base}/notifications`, { params: toParams({ unread_only: unreadOnly }) }),
    );
  }

  markRead(id: string): Promise<unknown> {
    return firstValueFrom(this.http.post(`${this.base}/notifications/${id}/read`, {}));
  }

  markAllRead(): Promise<unknown> {
    return firstValueFrom(this.http.post(`${this.base}/notifications/read-all`, {}));
  }
}
