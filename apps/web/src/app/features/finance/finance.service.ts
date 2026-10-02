import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  CashAccount,
  CashAccountInput,
  CashAccountUpdate,
  CashBook,
  ExpenseCategory,
  ExpenseCategoryInput,
  ExpensePosting,
  GeneralExpenseInput,
  GeneralExpensePage,
  JournalEntry,
  JournalEntryPage,
  OtherIncomeInput,
  OtherIncomePosting,
  Period,
  Preview,
  ReverseInput,
  ReverseResult,
  TransferInput,
  TransferPage,
  TransferPosting,
} from '../../core/api/api.models';

type Query = Record<string, string | number | boolean | null | undefined>;

function params(query: Query): HttpParams {
  let result = new HttpParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== null && value !== undefined && value !== '') {
      result = result.set(key, String(value));
    }
  }
  return result;
}

/** Calls to the cash, bank, journal and period endpoints (docs/API.md §3.2). */
@Injectable({ providedIn: 'root' })
export class FinanceService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  // --- Cash accounts and categories -------------------------------------------------
  cashAccounts(includeArchived = false): Promise<CashAccount[]> {
    return firstValueFrom(
      this.http.get<CashAccount[]>(`${this.base}/cash-accounts`, { params: params({ include_archived: includeArchived }) }),
    );
  }

  createCashAccount(body: CashAccountInput): Promise<CashAccount> {
    return firstValueFrom(this.http.post<CashAccount>(`${this.base}/cash-accounts`, body));
  }

  updateCashAccount(id: string, body: CashAccountUpdate): Promise<CashAccount> {
    return firstValueFrom(this.http.patch<CashAccount>(`${this.base}/cash-accounts/${id}`, body));
  }

  categories(kind?: 'GENERAL' | 'VEHICLE', includeArchived = false): Promise<ExpenseCategory[]> {
    return firstValueFrom(
      this.http.get<ExpenseCategory[]>(`${this.base}/expense-categories`, {
        params: params({ kind, include_archived: includeArchived }),
      }),
    );
  }

  createCategory(body: ExpenseCategoryInput): Promise<ExpenseCategory> {
    return firstValueFrom(this.http.post<ExpenseCategory>(`${this.base}/expense-categories`, body));
  }

  updateCategory(id: string, body: { archived?: boolean; name_ar?: string; name_en?: string }): Promise<ExpenseCategory> {
    return firstValueFrom(this.http.patch<ExpenseCategory>(`${this.base}/expense-categories/${id}`, body));
  }

  // --- Money-moving commands: preview, then post with an Idempotency-Key ----------------
  previewExpense(body: GeneralExpenseInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/general-expenses/preview`, body));
  }

  recordExpense(body: GeneralExpenseInput, idempotencyKey: string): Promise<ExpensePosting> {
    return firstValueFrom(
      this.http.post<ExpensePosting>(`${this.base}/general-expenses`, body, {
        headers: { 'Idempotency-Key': idempotencyKey },
      }),
    );
  }

  previewTransfer(body: TransferInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/transfers/preview`, body));
  }

  recordTransfer(body: TransferInput, idempotencyKey: string): Promise<TransferPosting> {
    return firstValueFrom(
      this.http.post<TransferPosting>(`${this.base}/transfers`, body, { headers: { 'Idempotency-Key': idempotencyKey } }),
    );
  }

  previewIncome(body: OtherIncomeInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/other-incomes/preview`, body));
  }

  recordIncome(body: OtherIncomeInput, idempotencyKey: string): Promise<OtherIncomePosting> {
    return firstValueFrom(
      this.http.post<OtherIncomePosting>(`${this.base}/other-incomes`, body, {
        headers: { 'Idempotency-Key': idempotencyKey },
      }),
    );
  }

  expenses(query: Query): Promise<GeneralExpensePage> {
    return firstValueFrom(this.http.get<GeneralExpensePage>(`${this.base}/general-expenses`, { params: params(query) }));
  }

  transfers(query: Query): Promise<TransferPage> {
    return firstValueFrom(this.http.get<TransferPage>(`${this.base}/transfers`, { params: params(query) }));
  }

  // --- Journal -------------------------------------------------------------------------------
  journalEntries(query: Query): Promise<JournalEntryPage> {
    return firstValueFrom(this.http.get<JournalEntryPage>(`${this.base}/journal-entries`, { params: params(query) }));
  }

  journalEntry(id: string): Promise<JournalEntry> {
    return firstValueFrom(this.http.get<JournalEntry>(`${this.base}/journal-entries/${id}`));
  }

  previewReverse(id: string, body: ReverseInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/journal-entries/${id}/reverse/preview`, body));
  }

  reverse(id: string, body: ReverseInput, idempotencyKey: string): Promise<ReverseResult> {
    return firstValueFrom(
      this.http.post<ReverseResult>(`${this.base}/journal-entries/${id}/reverse`, body, {
        headers: { 'Idempotency-Key': idempotencyKey },
      }),
    );
  }

  // --- Periods --------------------------------------------------------------------------------
  periods(): Promise<Period[]> {
    return firstValueFrom(this.http.get<Period[]>(`${this.base}/periods`));
  }

  lockPeriod(month: string): Promise<Period> {
    return firstValueFrom(this.http.post<Period>(`${this.base}/periods/${month}/lock`, {}));
  }

  unlockPeriod(month: string, reason: string): Promise<Period> {
    return firstValueFrom(this.http.post<Period>(`${this.base}/periods/${month}/unlock`, { reason }));
  }

  // --- Cash book ----------------------------------------------------------------------------------
  cashBook(cashAccountId: string, dateFrom: string, dateTo: string): Promise<CashBook> {
    return firstValueFrom(
      this.http.get<CashBook>(`${this.base}/reports/cash-book`, {
        params: params({ cash_account_id: cashAccountId, date_from: dateFrom, date_to: dateTo }),
      }),
    );
  }

  /** Downloads the cash book as Excel or PDF and hands the file to the browser. */
  async downloadCashBook(
    cashAccountId: string,
    dateFrom: string,
    dateTo: string,
    format: 'xlsx' | 'pdf',
    lang: 'ar' | 'en',
  ): Promise<void> {
    const response = await firstValueFrom(
      this.http.get(`${this.base}/reports/cash-book`, {
        params: params({ cash_account_id: cashAccountId, date_from: dateFrom, date_to: dateTo, format, lang }),
        responseType: 'blob',
        observe: 'response',
      }),
    );
    const disposition = response.headers.get('content-disposition') ?? '';
    const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `cash-book.${format}`;
    const url = URL.createObjectURL(response.body as Blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }
}
