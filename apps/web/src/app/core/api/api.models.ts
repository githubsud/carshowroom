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
export type TenantSettingsUpdate = Partial<Schemas['TenantSettingsUpdate']>;
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

// --- Partners (Phase 3) -------------------------------------------------------------------

export type Partner = Schemas['PartnerOut'];
export type PartnerInput = Schemas['PartnerIn'];
export type PartnerUpdate = Schemas['PartnerUpdate'];
export type PartnerSummary = Schemas['PartnerSummaryOut'];
export type PartnerSummaryRow = Schemas['PartnerSummaryRow'];
export type PartnerStatement = Schemas['PartnerStatementOut'];
export type PartnerPosition = Schemas['PartnerPosition'];
export type PartnerTransactionInput = Schemas['PartnerTransactionIn'];
export type PartnerTransaction = Schemas['PartnerTransactionOut'];
export type PartnerTransactionKind = PartnerTransactionInput['type'];
export type PartnerPosting = Schemas['PostingResult_PartnerTransactionOut_'];
export type ShareChangeInput = Schemas['ShareChangeIn'];
export type Share = Schemas['ShareOut'];
export type OtherIncomeInput = Schemas['OtherIncomeIn'];
export type OtherIncomePosting = Schemas['PostingResult_OtherIncomeOut_'];

// --- Vehicles, customers, suppliers, sales (Phase 4) -----------------------------------

export type Customer = Schemas['CustomerOut'];
export type CustomerInput = Schemas['CustomerIn'];
export type CustomerUpdate = Schemas['CustomerUpdate'];
export type CustomerDetail = Schemas['CustomerDetail'];
export type CustomerPage = Schemas['Page_CustomerOut_'];
export type CustomerRefundInput = Schemas['CustomerRefundIn'];
export type CustomerRefundPosting = Schemas['PostingResult_CustomerRefundOut_'];
export type Supplier = Schemas['SupplierOut'];
export type SupplierInput = Schemas['SupplierIn'];
export type SupplierStatement = Schemas['SupplierStatementOut'];
export type SupplierPaymentInput = Schemas['SupplierPaymentIn'];
export type SupplierPaymentPosting = Schemas['PostingResult_SupplierPaymentOut_'];
export type Location = Schemas['LocationOut'];
export type LocationInput = Schemas['LocationIn'];
export type Vehicle = Schemas['VehicleDetail'];
export type VehicleRow = Schemas['VehicleRow'];
export type VehiclePage = Schemas['VehiclePage'];
export type VehicleInput = Schemas['VehicleIn'];
export type VehicleUpdate = Schemas['VehicleUpdate'];
export type VehicleStatus = Vehicle['status'];
export type Aging = NonNullable<VehicleRow['aging']>;
export type PurchaseInput = Schemas['PurchaseIn'];
export type PurchasePosting = Schemas['PostingResult_PurchaseOut_'];
export type SellerPaymentInput = Schemas['SellerPaymentIn'];
export type SellerPaymentPosting = Schemas['PostingResult_SellerPaymentOut_'];
export type VehicleExpenseInput = Schemas['VehicleExpenseIn'];
export type VehicleExpensePosting = Schemas['PostingResult_VehicleExpenseOut_'];
export type UploadTicket = Schemas['UploadTicket'];
export type VehicleDocument = Schemas['DocumentOut'];
export type DocumentType = VehicleDocument['doc_type'];
export type SearchResult = Schemas['SearchOut'];
export type Reservation = Schemas['ReservationOut'];
export type ReservationInput = Schemas['ReservationIn'];
export type ReservationSettleInput = Schemas['ReservationSettleIn'];
export type ReservationPosting = Schemas['PostingResult_ReservationOut_'];
export type Sale = Schemas['SaleOut'];
export type SaleDraftInput = Schemas['SaleDraftIn'];
export type SaleListRow = Schemas['SaleListRow'];
export type SalePage = Schemas['SalePage'];
export type SalePosting = Schemas['PostingResult_SaleOut_'];
export type SaleCancelInput = Schemas['SaleCancelIn'];
export type TradeInInput = Schemas['TradeInIn'];
