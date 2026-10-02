/**
 * API contracts. Request/response types are generated from the FastAPI OpenAPI
 * schema (`npm run api:types`, BACKLOG 1.10); this file only gives them short
 * names. Never edit schema.d.ts by hand: CI regenerates it and fails on drift.
 */
import type { components } from './schema';

type Schemas = components['schemas'];

// --- Errors (shared envelope, SPEC §8) ---------------------------------------------

export interface ApiErrorBody {
  error: { code: string; message: string; details: Record<string, unknown> };
}

/** An API error with its stable code; the UI translates the code (SPEC §8). */
export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

// --- Session, tenant, users ------------------------------------------------------------

export type Me = Schemas['MeOut'];
export type Membership = Schemas['MembershipOut'];
export type Tenant = Schemas['TenantOut'];
export type TenantSettings = Schemas['TenantSettingsOut'];
export type DigitStyle = TenantSettings['digit_style'];
export type Member = Schemas['MemberOut'];
export type Role = Schemas['RoleOut'];

// --- Finance (Phase 2) -------------------------------------------------------------------

export type CashAccount = Schemas['CashAccountOut'];
export type CashAccountInput = Schemas['CashAccountIn'];
export type CashAccountUpdate = Schemas['CashAccountUpdate'];
export type ExpenseCategory = Schemas['ExpenseCategoryOut'];
export type ExpenseCategoryInput = Schemas['ExpenseCategoryIn'];
export type GeneralExpenseInput = Schemas['GeneralExpenseIn'];
export type GeneralExpense = Schemas['GeneralExpenseOut'];
export type TransferInput = Schemas['TransferIn'];
export type Transfer = Schemas['TransferOut'];
export type Preview = Schemas['Preview'];
export type PostingWarning = Schemas['PostingWarning'];
export type ExpensePosting = Schemas['PostingResult_GeneralExpenseOut_'];
export type TransferPosting = Schemas['PostingResult_TransferOut_'];
export type CashBook = Schemas['CashBookOut'];
export type CashBookMovement = Schemas['CashBookMovement'];
export type JournalEntry = Schemas['JournalEntryOut'];
export type JournalEntryPage = Schemas['Page_JournalEntryOut_'];
export type GeneralExpensePage = Schemas['Page_GeneralExpenseOut_'];
export type TransferPage = Schemas['Page_TransferOut_'];
export type ReverseInput = Schemas['ReverseIn'];
export type ReverseResult = Schemas['ReverseOut'];
export type Period = Schemas['PeriodOut'];
export type LedgerAccount = Schemas['LedgerAccountOut'];
