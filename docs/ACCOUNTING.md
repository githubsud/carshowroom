# ACCOUNTING: Financial Model and Posting Rules

> Phase 0 design. Labels: **FACT** / **ASSUMPTION** / **DECISION** / **OPEN QUESTION** ([DECISIONS.md](DECISIONS.md)).
> This document uses "Dr/Cr" because it is written for accountants and developers. **The UI never shows these words to non-accountant roles** (FACT, SPEC §9.3).
> **No accounting, tax or legal rule has been invented here.** Every rule numbered 1–35 comes from SPEC §7. Where the spec is silent or contradictory, §5 lists the gap as an **OPEN QUESTION**, with a *candidate treatment* for the owner's accountant to confirm. Nothing in §5 is implemented until it is approved.

---

## 1. Principles

| # | Principle | Label |
|---|---|---|
| 1 | Double entry: every journal entry has ≥ 2 lines and Σ Dr = Σ Cr, enforced in the DB at commit | FACT |
| 2 | Money is `numeric(18,2)` / `Decimal`, rounded ROUND_HALF_UP to 2 dp. Rounding happens once, at the line level, before balance checks | FACT / DECISION |
| 3 | Posted entries are immutable. Corrections happen only by reversal (rule 24) plus re-entry | FACT |
| 4 | Balances (cash, partner, vehicle cost, receivables) are always derived from `journal_lines` | FACT |
| 5 | Every line that hits a subledger account carries the subledger id (partner, customer, vehicle, consignor, external showroom, supplier, cash account) | FACT |
| 6 | Vehicle cost = Σ Dr − Σ Cr on account 1300 for that `vehicle_id`. The vehicle file's cost breakdown is the list of those lines | DECISION D-26 |
| 7 | Vehicle gross profit = Vehicle Sales (4100) − COGS (5000) for that `vehicle_id`, less 6100 commission for externally sold cars (Q-34). Consignment-in profit = 4200 for that vehicle | FACT (§4.9), ASSUMPTION for 6100 |
| 8 | Posting rules are pure Python functions with unit tests written **before** the endpoints (SPEC §0.4) | FACT |
| 9 | The posting date is the document date (tenant timezone) and must fall in an OPEN period | FACT |

---

## 2. Chart of accounts (seed template)

**FACT (SPEC §6)** for codes and names. The Arabic names are our proposal; Egyptian/Gulf variants are Q-25. "Postable" means lines may be posted to the account. **DECISION D-27:** headers are not postable; sub-accounts are created automatically (one per cash box or bank account, one per general-expense category).

| Code | English | Arabic | Type | Normal | Subledger | Postable |
|---|---|---|---|---|---|---|
| 1000 | Assets | الأصول | Asset | Dr | | header |
| 1100 | Cash boxes | الخزائن | Asset | Dr | | header |
| 1101… | *one per cash box* (e.g. Main cash box) | الخزنة الرئيسية | Asset | Dr | CASH_ACCOUNT | ✓ |
| 1200 | Bank accounts | الحسابات البنكية | Asset | Dr | | header |
| 1201… | *one per bank account* | حساب بنك … | Asset | Dr | CASH_ACCOUNT | ✓ |
| 1300 | Vehicle inventory | مخزون السيارات | Asset | Dr | VEHICLE | ✓ |
| 1400 | Installment receivables | أقساط مستحقة على العملاء | Asset | Dr | CUSTOMER | ✓ |
| 1410 | Other receivables | مدينون آخرون | Asset | Dr | CUSTOMER | ✓ |
| 1420 | Receivable from external showrooms | مستحقات لدى المعارض الأخرى | Asset | Dr | EXTERNAL_SHOWROOM | ✓ |
| 1430 | Recoverable expenses from consignors | مصاريف مستردة من أصحاب سيارات الأمانة | Asset | Dr | CONSIGNOR | ✓ |
| 1500 | Loans/advances to partners | سلف الشركاء | Asset | Dr | PARTNER | ✓ |
| 2000 | Liabilities | الالتزامات | Liability | Cr | | header |
| 2100 | Payable to sellers (deferred purchase price) | مستحقات للبائعين | Liability | Cr | CUSTOMER (+vehicle) | ✓ |
| 2200 | Payable to consignors | مستحقات لأصحاب سيارات الأمانة | Liability | Cr | CONSIGNOR | ✓ |
| 2300 | Customer deposits | عرابين العملاء | Liability | Cr | CUSTOMER (+vehicle) | ✓ |
| 2310 | Customer credits / refunds owed (D-41) | أرصدة دائنة للعملاء / مبالغ مستحقة الرد | Liability | Cr | CUSTOMER | ✓ |
| 2400 | Deferred installment income (markup mode only) | إيرادات تقسيط مؤجلة | Liability | Cr | CUSTOMER | ✓ |
| 2500 | Taxes payable | ضرائب مستحقة | Liability | Cr | | ✓ (unused until Q-11) |
| 2600 | Loans from partners | قروض من الشركاء | Liability | Cr | PARTNER | ✓ |
| 2700 | Payable to suppliers | مستحقات للموردين | Liability | Cr | SUPPLIER | ✓ |
| 3000 | Equity | حقوق الملكية | Equity | Cr | | header |
| 3100 | Partner capital | رأس مال الشركاء | Equity | Cr | PARTNER | ✓ |
| 3200 | Partner current accounts | جاري الشركاء | Equity | Cr | PARTNER | ✓ |
| 3300 | Retained earnings / undistributed profit | أرباح غير موزعة | Equity | Cr | | ✓ |
| 3310 | Profit allocated in advance (per-car policy only, D-40) | أرباح موزعة مقدماً | Equity | Dr (contra) | | ✓ |
| 3900 | Opening balance equity | أرصدة افتتاحية | Equity | Cr | | ✓ |
| 4000 | Income | الإيرادات | Income | Cr | | header |
| 4100 | Vehicle sales | مبيعات السيارات | Income | Cr | VEHICLE | ✓ |
| 4200 | Consignment commission income | عمولات بيع سيارات الأمانة | Income | Cr | VEHICLE | ✓ |
| 4300 | Installment financing income | إيرادات التقسيط | Income | Cr | CUSTOMER | ✓ |
| 4900 | Other income | إيرادات أخرى | Income | Cr | | ✓ |
| 5000 | Cost of vehicles sold | تكلفة السيارات المباعة | Expense | Dr | VEHICLE | ✓ (DECISION: 5000 is postable, as in the spec) |
| 6000 | Expenses | المصروفات | Expense | Dr | | header |
| 6100 | Commission paid to external showrooms | عمولات المعارض الأخرى | Expense | Dr | VEHICLE + EXTERNAL_SHOWROOM | ✓ |
| 6210 | Rent | إيجار | Expense | Dr | | ✓ |
| 6220 | Salaries | مرتبات | Expense | Dr | | ✓ |
| 6230 | Utilities | مرافق (كهرباء، مياه، إنترنت) | Expense | Dr | | ✓ |
| 6240 | Advertising agency | دعاية وإعلان | Expense | Dr | | ✓ |
| 6250 | Government fees | رسوم حكومية | Expense | Dr | | ✓ |
| 6260 | Tips (إكرامية) | إكراميات | Expense | Dr | | ✓ |
| 6270 | Bank charges (P-07, added in Phase 5) | مصاريف بنكية | Expense | Dr | | ✓ |
| 6280 | Consigned-car expenses borne by the showroom (P-05, added in Phase 6; vehicle subledger) | مصاريف سيارات الأمانة على المعرض | Expense | Dr | | ✓ |
| 6290 | Other general expenses | مصروفات عامة أخرى | Expense | Dr | | ✓ |

**ASSUMPTION.** Codes 6210–6290 for the seeded general categories are our numbering; the spec only says "6200..". A tenant-added category gets the next free 62xx code.

**FACT (SPEC §4.1).** Vehicle expense categories (maintenance, bodywork, paint, polishing, cleaning, license renewal, transport, inspection, tips, other) do **not** have their own ledger accounts. On OWNED cars they are capitalized into 1300. The category is stored on the document and the line memo for the cost breakdown.

**Notation in examples.** One tenant in EGP. Cash box "Main" = 1101, bank "CIB" = 1201. Partners: Ahmed 50%, Mona 30%, Youssef 20%. `(V1)` means the line carries `vehicle_id` V1, and `(Ahmed)` means it carries that `partner_id`.

---

## 3. Posting rules 1–35 with worked examples

### Partners and capital

**Rule 1: Partner capital contribution.** Ahmed deposits 1,000,000 into CIB.

| Account | Dr | Cr |
|---|---:|---:|
| 1201 Bank CIB | 1,000,000.00 | |
| 3100 Partner capital (Ahmed) | | 1,000,000.00 |

**Rule 2: Partner capital withdrawal.** Ahmed withdraws 100,000 of capital in cash. (The effect on ownership % is Q-19.)

| Account | Dr | Cr |
|---|---:|---:|
| 3100 Partner capital (Ahmed) | 100,000.00 | |
| 1101 Main cash box | | 100,000.00 |

**Rule 3: Partner drawing from share.** Ahmed takes 50,000 cash against his share. (Whether "سحب من الحصة" means capital or profit is Q-04.)

| Account | Dr | Cr |
|---|---:|---:|
| 3200 Partner current account (Ahmed) | 50,000.00 | |
| 1101 Main cash box | | 50,000.00 |

**Rule 4: Loan/advance to partner.** Mona borrows 30,000 cash.

| Account | Dr | Cr |
|---|---:|---:|
| 1500 Loans to partners (Mona) | 30,000.00 | |
| 1101 Main cash box | | 30,000.00 |

**Rule 5: Partner loan repayment.** Mona repays 10,000. Her outstanding loan is now 20,000.

| Account | Dr | Cr |
|---|---:|---:|
| 1101 Main cash box | 10,000.00 | |
| 1500 Loans to partners (Mona) | | 10,000.00 |

**Rule 28: Partner lends money to the business.** Youssef lends 100,000 into CIB.

| Account | Dr | Cr |
|---|---:|---:|
| 1201 Bank CIB | 100,000.00 | |
| 2600 Loans from partners (Youssef) | | 100,000.00 |

**Rule 29: Business repays partner loan.** 40,000 is repaid to Youssef from CIB. 60,000 remains owed to him.

| Account | Dr | Cr |
|---|---:|---:|
| 2600 Loans from partners (Youssef) | 40,000.00 | |
| 1201 Bank CIB | | 40,000.00 |

**Rule 30: Partner pays an expense personally.** Ahmed personally pays 3,000 transport for owned car V6. The user chooses per transaction (FACT §4.2):

*(a) Credited to his current account:*

| Account | Dr | Cr |
|---|---:|---:|
| 1300 Vehicle inventory (V6) | 3,000.00 | |
| 3200 Partner current account (Ahmed) | | 3,000.00 |

*(b) Recorded as a loan from him:*

| Account | Dr | Cr |
|---|---:|---:|
| 1300 Vehicle inventory (V6) | 3,000.00 | |
| 2600 Loans from partners (Ahmed) | | 3,000.00 |

For a general expense, the Dr line is the 62xx category account instead (for example, Dr 6230 Utilities). For a **consigned-in** car, the spec's rule 30 still says "Vehicle Inventory"; this contradicts rule 10 (C-11, Q-15).

### Purchases and vehicle expenses

**Rule 6: Buy car (paid).** V1 (Hyundai Elantra 2019) is bought for 400,000 from CIB.

| Account | Dr | Cr |
|---|---:|---:|
| 1300 Vehicle inventory (V1) | 400,000.00 | |
| 1201 Bank CIB | | 400,000.00 |

**Rule 7: Buy car (partly deferred).** V2 is bought from seller Karim for 500,000: 300,000 cash now and 200,000 later.

| Account | Dr | Cr |
|---|---:|---:|
| 1300 Vehicle inventory (V2) | 500,000.00 | |
| 1101 Main cash box | | 300,000.00 |
| 2100 Payable to sellers (Karim, V2) | | 200,000.00 |

**DECISION.** 2100 lines carry the seller's `customer_id` and the `vehicle_id`, so we can answer "what do we still owe for which car".

**Rule 8: Pay seller later.** Karim is paid 200,000 from CIB.

| Account | Dr | Cr |
|---|---:|---:|
| 2100 Payable to sellers (Karim, V2) | 200,000.00 | |
| 1201 Bank CIB | | 200,000.00 |

**Rule 9: Expense on an OWNED car.** Paint for V1 costs 15,000 cash. V1's cost is now 415,000.

| Account | Dr | Cr |
|---|---:|---:|
| 1300 Vehicle inventory (V1) — memo "Paint" | 15,000.00 | |
| 1101 Main cash box | | 15,000.00 |

**Rule 10: Expense on a CONSIGNED-IN car, paid by the showroom.** Cleaning V3 (owner: Samir) costs 2,000 cash.

| Account | Dr | Cr |
|---|---:|---:|
| 1430 Recoverable from consignors (Samir, V3) | 2,000.00 | |
| 1101 Main cash box | | 2,000.00 |

**Rule 31: Expense or service on credit.** Workshop "Al-Amal Garage" repairs V7 for 12,000, payable later.

| Account | Dr | Cr |
|---|---:|---:|
| 1300 Vehicle inventory (V7) — memo "Maintenance" | 12,000.00 | |
| 2700 Payable to suppliers (Al-Amal Garage) | | 12,000.00 |

The same rule applies to a general expense on credit (Dr 62xx). For consigned-in cars, see C-11.

**Rule 32: Pay supplier.** Al-Amal Garage is paid 12,000 cash.

| Account | Dr | Cr |
|---|---:|---:|
| 2700 Payable to suppliers (Al-Amal Garage) | 12,000.00 | |
| 1101 Main cash box | | 12,000.00 |

### Deposits and sales

**Rule 11: Customer deposit received.** Hassan pays a 20,000 cash deposit to reserve V1.

| Account | Dr | Cr |
|---|---:|---:|
| 1101 Main cash box | 20,000.00 | |
| 2300 Customer deposits (Hassan, V1) | | 20,000.00 |

**Rule 12: Cash sale of an owned car.** V1 (cost 415,000) is sold to Hassan for 480,000. The 20,000 deposit is applied, and 460,000 comes by bank transfer.

*Entry A (sale):*

| Account | Dr | Cr |
|---|---:|---:|
| 1201 Bank CIB | 460,000.00 | |
| 2300 Customer deposits (Hassan, V1) | 20,000.00 | |
| 4100 Vehicle sales (V1) | | 480,000.00 |

*Entry B (cost recognition, same transaction; the amount is the derived 1300 balance for V1):*

| Account | Dr | Cr |
|---|---:|---:|
| 5000 Cost of vehicles sold (V1) | 415,000.00 | |
| 1300 Vehicle inventory (V1) | | 415,000.00 |

The gross profit on V1 is 480,000 − 415,000 = **65,000** (13.54% of the sale price).

**DECISION D-28.** The sale and its cost recognition are **two journal entries** posted in one DB transaction and linked by `source_id`. This keeps the "sale" and "cost" views clean, and reversal reverses both. (A single combined entry is equally valid; we chose two for readability.)

**Rule 13: Installment sale (mode a).** V2 (cost 500,000) is sold to Mariam for 600,000: 150,000 cash down payment, with the remaining 450,000 in 6 monthly installments of 75,000.

| Account | Dr | Cr |
|---|---:|---:|
| 1101 Main cash box | 150,000.00 | |
| 1400 Installment receivables (Mariam) | 450,000.00 | |
| 4100 Vehicle sales (V2) | | 600,000.00 |

| Account | Dr | Cr |
|---|---:|---:|
| 5000 Cost of vehicles sold (V2) | 500,000.00 | |
| 1300 Vehicle inventory (V2) | | 500,000.00 |

Schedule rule (FACT, SPEC §4.8): equal split, with the rounding remainder on the **last** installment. For example, if the same 450,000 were split into 7 installments: 450,000 ÷ 7 = 64,285.71, the first 6 total 385,714.26, so the last installment is 64,285.74.

**Rule 14: Installment sale (mode b, markup).** The cash price is 600,000 and the financing markup is 60,000. A down payment of 150,000 leaves a receivable of 450,000 + 60,000 = 510,000 (6 × 85,000).

| Account | Dr | Cr |
|---|---:|---:|
| 1101 Main cash box | 150,000.00 | |
| 1400 Installment receivables (Mariam) | 510,000.00 | |
| 4100 Vehicle sales (V2) | | 600,000.00 |
| 2400 Deferred installment income (Mariam) | | 60,000.00 |

Cost recognition is the same as in rule 13.

**Rule 15: Installment collected.**

*Mode a:* Mariam pays installment #1, 75,000 cash.

| Account | Dr | Cr |
|---|---:|---:|
| 1101 Main cash box | 75,000.00 | |
| 1400 Installment receivables (Mariam) | | 75,000.00 |

*Mode b:* Mariam pays installment #1, 85,000 cash. The markup portion is then recognized. **The recognition method is an OPEN QUESTION (Q-03).** The figures below are **illustrative only** and use a proportional split: 60,000 / 510,000 × 85,000 = 10,000.

| Account | Dr | Cr |
|---|---:|---:|
| 1101 Main cash box | 85,000.00 | |
| 1400 Installment receivables (Mariam) | | 85,000.00 |
| 2400 Deferred installment income (Mariam) | 10,000.00 | |
| 4300 Installment financing income (Mariam) | | 10,000.00 |

**Rule 27: Post-dated cheque bounced (after being recorded as collected).** Mariam's 75,000 cheque, already recorded as collected into CIB, bounces. Installment #2 reopens, and the customer is flagged.

| Account | Dr | Cr |
|---|---:|---:|
| 1400 Installment receivables (Mariam) | 75,000.00 | |
| 1201 Bank CIB | | 75,000.00 |

**ASSUMPTION A-10.** A cheque is recorded as collected (rule 15) only when its status becomes `COLLECTED`. A cheque that bounces while still `HELD` or `DEPOSITED` therefore produces **no** journal entry, only a status change. Bank charges on a bounced cheque have no rule (Q-20).

**Rule 26: Sale with trade-in.** V6 (cost 450,000) is sold to Omar for 550,000. Omar trades in his car (new record V7, source `TRADE_IN`) at an agreed value of 200,000 and pays 350,000 by bank.

| Account | Dr | Cr |
|---|---:|---:|
| 1201 Bank CIB | 350,000.00 | |
| 1300 Vehicle inventory (V7, trade-in) | 200,000.00 | |
| 4100 Vehicle sales (V6) | | 550,000.00 |

| Account | Dr | Cr |
|---|---:|---:|
| 5000 Cost of vehicles sold (V6) | 450,000.00 | |
| 1300 Vehicle inventory (V6) | | 450,000.00 |

The profit on V6 is 550,000 − 450,000 = **100,000**. V7's cost file starts at **200,000**, and later expenses on V7 add to it (rule 9). V7 also gets a `vehicle_purchases` record with seller = Omar, price 200,000, `source_type = SALE_TRADE_IN`, and no separate journal entry.

**Rule 34: Deposit refunded.** Hassan's 20,000 deposit is refunded in cash.

| Account | Dr | Cr |
|---|---:|---:|
| 2300 Customer deposits (Hassan, V1) | 20,000.00 | |
| 1101 Main cash box | | 20,000.00 |

**Rule 35: Deposit forfeited.** Hassan cancels, and the 20,000 deposit is kept.

| Account | Dr | Cr |
|---|---:|---:|
| 2300 Customer deposits (Hassan, V1) | 20,000.00 | |
| 4900 Other income | | 20,000.00 |

**Rule 33: Sale cancellation.** The rule-12 sale of V1 is cancelled. The spec says the cancellation is "reversal of the original sale entries", so mirror entries are posted on the cancellation date:

| Account | Dr | Cr |
|---|---:|---:|
| 4100 Vehicle sales (V1) | 480,000.00 | |
| 1201 Bank CIB | | 460,000.00 |
| 2300 Customer deposits (Hassan, V1) | | 20,000.00 |

| Account | Dr | Cr |
|---|---:|---:|
| 1300 Vehicle inventory (V1) | 415,000.00 | |
| 5000 Cost of vehicles sold (V1) | | 415,000.00 |

V1 returns to inventory at 415,000, and the deposit liability of 20,000 is restored. Rule 34 or rule 35 then settles the deposit.

> ⚠ **Contradiction C-06.** The literal mirror **credits the bank 460,000 on the cancellation date**, as if the money had already been refunded. SPEC §4.7 says refunds are "separate transactions". If the customer has not been refunded yet, or is refunded partly or from a different account, the bank balance is wrong. Installment collections received after the sale are not in the original entry at all, so after the reversal 1400 would show a credit balance. **OPEN QUESTION Q-12**, with a candidate treatment in §5.

### Consignment

**Rule 16: Sale of a consigned-in car.** V3 (owner Samir; commission 5%; recoverable expenses 2,000 from rule 10) is sold for 300,000 by bank.

*Entry A:*

| Account | Dr | Cr |
|---|---:|---:|
| 1201 Bank CIB | 300,000.00 | |
| 2200 Payable to consignors (Samir, V3) | | 300,000.00 |

*Entry B (commission and recovery):* commission = 5% × 300,000 = 15,000.

| Account | Dr | Cr |
|---|---:|---:|
| 2200 Payable to consignors (Samir, V3) | 17,000.00 | |
| 4200 Consignment commission income (V3) | | 15,000.00 |
| 1430 Recoverable from consignors (Samir, V3) | | 2,000.00 |

The amount due to Samir is 300,000 − 15,000 − 2,000 = **283,000** (FACT, SPEC §4.4). The showroom's profit on V3 is **15,000**.

For **net-price terms** (the agreed net to the owner is 280,000): commission = sale price − net price = 300,000 − 280,000 = 20,000. Our reading is that recoverable expenses are still deducted from the amount paid to the owner (then 278,000 is due). This must be confirmed, as must the case where the car sells **below** the net price (Q-15).

**Rule 17: Pay consignor.** Samir is paid 283,000 from CIB.

| Account | Dr | Cr |
|---|---:|---:|
| 2200 Payable to consignors (Samir, V3) | 283,000.00 | |
| 1201 Bank CIB | | 283,000.00 |

**Rule 18: Our car sold by an external showroom.** V4 (cost 350,000) is at "Al-Amal Motors" (commission 8,000) and they sell it for 400,000.

| Account | Dr | Cr |
|---|---:|---:|
| 1420 Receivable from external showrooms (Al-Amal Motors) | 400,000.00 | |
| 4100 Vehicle sales (V4) | | 400,000.00 |

| Account | Dr | Cr |
|---|---:|---:|
| 6100 Commission to external showrooms (V4, Al-Amal Motors) | 8,000.00 | |
| 1420 Receivable from external showrooms (Al-Amal Motors) | | 8,000.00 |

| Account | Dr | Cr |
|---|---:|---:|
| 5000 Cost of vehicles sold (V4) | 350,000.00 | |
| 1300 Vehicle inventory (V4) | | 350,000.00 |

The net receivable is 392,000. The gross profit on V4 is 400,000 − 350,000 = 50,000, or 42,000 after commission. Which figure the vehicle file shows as "profit" is Q-34; the default is **after** commission.

**Rule 19: Collect from the external showroom.** 392,000 is received into CIB.

| Account | Dr | Cr |
|---|---:|---:|
| 1201 Bank CIB | 392,000.00 | |
| 1420 Receivable from external showrooms (Al-Amal Motors) | | 392,000.00 |

### Cash, bank and general

**Rule 20: General expense.** Monthly rent of 25,000 is paid from CIB.

| Account | Dr | Cr |
|---|---:|---:|
| 6210 Rent | 25,000.00 | |
| 1201 Bank CIB | | 25,000.00 |

**Rule 21: Cash ↔ bank transfer.** 100,000 cash is deposited into CIB.

| Account | Dr | Cr |
|---|---:|---:|
| 1201 Bank CIB (destination) | 100,000.00 | |
| 1101 Main cash box (source) | | 100,000.00 |

### Period close, distribution, reversal, opening

**Rule 23: Period close (income summary).** For the period: 4100 = 480,000, 4200 = 15,000, 5000 = 415,000 and 6210 = 25,000, so net profit = 480,000 + 15,000 − 415,000 − 25,000 = **55,000**.

| Account | Dr | Cr |
|---|---:|---:|
| 4100 Vehicle sales | 480,000.00 | |
| 4200 Consignment commission income | 15,000.00 | |
| 5000 Cost of vehicles sold | | 415,000.00 |
| 6210 Rent | | 25,000.00 |
| 3300 Retained earnings / undistributed profit | | 55,000.00 |

The entry is flagged `is_closing = true`, and **DECISION D-29:** the P&L excludes closing entries, so it still shows the period's activity. If the period made a loss, 3300 is debited. The closing frequency (monthly or only at distribution) is Q-27.

**Rule 22: Profit distribution.** 55,000 of undistributed profit is split 50/30/20.

| Account | Dr | Cr |
|---|---:|---:|
| 3300 Retained earnings / undistributed profit | 55,000.00 | |
| 3200 Partner current account (Ahmed) | | 27,500.00 |
| 3200 Partner current account (Mona) | | 16,500.00 |
| 3200 Partner current account (Youssef) | | 11,000.00 |

Cash payout is a separate rule-3 drawing (FACT §4.9).

*Pro-rata when percentages change mid-period (FACT: pro-rate; the **method** is Q-18). This example is illustrative only and uses day weighting.* January has 31 days. Ahmed holds 50% on days 1–15 and 40% on days 16–31. Mona holds 30% then 40%. Youssef holds 20% throughout. Net profit is 100,000.

- Ahmed: (50 × 15 + 40 × 16) / 31 = 44.8387% → 44,838.71
- Mona: (30 × 15 + 40 × 16) / 31 = 35.1613% → 35,161.29
- Youssef: 20% → 20,000.00
- Σ = 100,000.00 ✓. Any rounding remainder goes to the partner with the largest fractional part (Q-18).

An alternative is to compute actual profit per sub-period (days 1–15 and 16–31 separately). It gives different numbers whenever profit is uneven within the month, so the choice is the owner's.

**Rule 24: Reversal of any entry.** The rule-20 rent entry (#57) was posted to the wrong account. The reversal entry #58, with `reversal_of_id = #57` and a mandatory reason, is:

| Account | Dr | Cr |
|---|---:|---:|
| 1201 Bank CIB | 25,000.00 | |
| 6210 Rent | | 25,000.00 |

Entry #57 gets `reversed_by_id = #58`. A corrected entry is then posted. **DECISION:** the reversal is dated on a user-chosen date (default today), which must fall in an OPEN period. An entry that has already been reversed cannot be reversed again. A reversal entry itself cannot be reversed; the user re-posts the original transaction instead.

**Rule 25: Opening balances (import).** At go-live the showroom has 200,000 cash, 800,000 in CIB, vehicle V5 at 300,000 cost (purchase plus opening expenses), Mariam's open installments of 120,000 and 50,000 still owed to seller Karim. Partner capital is Ahmed 600,000 and Mona 400,000.

| Account | Dr | Cr |
|---|---:|---:|
| 1101 Main cash box | 200,000.00 | |
| 1201 Bank CIB | 800,000.00 | |
| 1300 Vehicle inventory (V5) | 300,000.00 | |
| 1400 Installment receivables (Mariam) | 120,000.00 | |
| 2100 Payable to sellers (Karim) | | 50,000.00 |
| 3100 Partner capital (Ahmed) | | 600,000.00 |
| 3100 Partner capital (Mona) | | 400,000.00 |
| 3900 Opening balance equity | | 370,000.00 |

Σ Dr = Σ Cr = 1,420,000. The entry is flagged `is_opening`. **Where the 370,000 opening balance equity ends up (partner current accounts? retained earnings?) is Q-16.** If it stays on 3900, the check that partner balances plus liabilities equal assets fails (C-07).

---

## 4. Full scenario test (SPEC §7), with hand-calculated expected values

Partners: A 50%, B 30%, C 20%. One period, and all figures are in EGP.

| Step | Event | Rule | Cash 1101 | Bank 1201 |
|---|---|---|---:|---:|
| 1 | A contributes 1,000,000, B 600,000, C 400,000 to the bank | 1 | 0 | 2,000,000 |
| 2 | Buy Car1 400,000, Car2 500,000, Car3 300,000 from the bank | 6 | 0 | 800,000 |
| 3 | Transfer 100,000 bank → cash | 21 | 100,000 | 700,000 |
| 4 | Expenses in cash: Car1 10,000, Car2 20,000, Car3 5,000 (costs 410,000 / 520,000 / 305,000) | 9 | 65,000 | 700,000 |
| 5 | Sell Car1 for cash at 480,000 (COGS 410,000) | 12 | 545,000 | 700,000 |
| 6 | Sell Car2 on installments (mode a) at 640,000: 160,000 down in cash + 6 × 80,000 (COGS 520,000) | 13 | 705,000 | 700,000 |
| 7 | Car3 consigned out; the external showroom sells it at 360,000, commission 10,000 (COGS 305,000) | 18 | 705,000 | 700,000 |
| 8 | Collect 2 installments, 2 × 80,000 in cash | 15 | 865,000 | 700,000 |
| 9 | B draws 20,000 in cash | 3 | 845,000 | 700,000 |
| 10 | Loan to partner C, 30,000 in cash | 4 | 815,000 | 700,000 |
| 11 | Close the period: net profit = 1,480,000 − 1,235,000 − 10,000 = 235,000 | 23 | | |
| 12 | Distribute 235,000: A 117,500, B 70,500, C 47,000 | 22 | | |

**Expected balances after step 12:**

| Item | Expected |
|---|---:|
| Cash (1101) | 815,000.00 |
| Bank (1201) | 700,000.00 |
| Vehicle inventory (1300) | 0.00 |
| Installment receivable, Car2 buyer (1400) | 320,000.00 |
| Receivable from the external showroom (1420) | 350,000.00 |
| Loans to partners (1500), C | 30,000.00 |
| **Total assets** | **2,215,000.00** |
| Liabilities | 0.00 |
| Capital (3100): A 1,000,000 / B 600,000 / C 400,000 | 2,000,000.00 |
| Current accounts (3200): A 117,500 / B 50,500 / C 47,000 | 215,000.00 |
| Retained earnings (3300) | 0.00 |
| **Total liabilities + equity** | **2,215,000.00** ✓ |

P&L: sales 1,480,000; COGS 1,235,000; **gross profit 245,000** (Car1 70,000, Car2 120,000, Car3 55,000); commission expense 10,000; **net profit 235,000**.

Partner net position (candidate formula, Q-17: capital + current account − loans to partner + loans from partner):

| Partner | Calculation | Net position |
|---|---|---:|
| A | 1,000,000 + 117,500 | 1,117,500 |
| B | 600,000 + 50,500 | 650,500 |
| C | 400,000 + 47,000 − 30,000 | 417,000 |

---

**As built (Phase 7):** `tests/integration/test_full_scenario.py` runs steps 1–12 through the services in a fresh showroom and asserts every value above exactly.

---

## 5. Open accounting questions (not implemented until answered)

The spec has no rule for each event below. The **candidate treatment** is a proposal for the owner's accountant to approve or replace. It is not a rule.

| ID | Event / gap | Candidate treatment (to confirm) | Link |
|---|---|---|---|
| P-01 | Other income received (§4.10 module, no rule) | Dr Cash/Bank / Cr 4900 Other income | G-01. **Approved (Q-26); implemented in Phase 3** |
| P-02 | Customer overpayment kept as credit (business rule 3) | **Refund leg implemented in Phase 4; overpayment as credit arrives with Phase 5 payments.** **Approved as tenant option (D-41)**: `BLOCK` (default) or `ALLOW_AS_CREDIT` → Dr Cash / Cr 2310 (customer); later applied or refunded (Dr 2310 / Cr Cash) | G-02, Q-13 |
| P-03 | Sale cancellation without an immediate refund (fixes C-06) | **Implemented in Phase 4 (both methods).** **Approved as tenant option (D-41)**: `REFUND_LIABILITY` (default) reverses revenue and cost, and all amounts received move to 2310; the refund is posted separately. `MIRROR` = literal rule 33 | C-06, Q-12 |
| P-04 | Expense recorded on a car that is already SOLD | Dr 5000 COGS (vehicle) / Cr Cash; the car's profit is recalculated | G-03, Q-14. **Approved (Q-26); implemented in Phase 4** |
| P-05 | Expense on a consigned-in car **borne by the showroom** (terms: showroom/shared) | Dr a showroom expense account (not specified in the COA) / Cr Cash; for the shared portion, split between 1430 and the expense | G-10, Q-15. **Approved (Q-26); implemented in Phase 6 with the new account 6280 Consigned-car expenses (D-93)** |
| P-06 | Consignor reimburses recoverable expenses when the car is returned unsold (§4.4 "settle any recoverable expenses") | Dr Cash / Cr 1430 (consignor) | G-10. **Approved (Q-26); implemented in Phase 6 (D-96)** |
| P-07 | Bank charges on a bounced cheque, possibly recharged to the customer | Dr bank-charges expense (no account in the COA) / Cr Bank; optionally Dr 1410 (customer) | Q-20. **Approved (Q-26); implemented in Phase 5 with the new account 6270 (D-85)** |
| P-08 | Clearing Opening Balance Equity 3900 | Allocate to partner capital or current accounts by agreement | Q-16. **Approved (Q-26); implemented in Phase 8 (D-112)** |
| P-09 | Distribution of a **loss** | **Approved as tenant option (D-40)**: `ALLOCATE_TO_PARTNERS` (default) Dr 3200 per partner / Cr 3300 by %; or `CARRY_FORWARD` (stays in 3300) | G-07. **Implemented in Phase 7** |
| P-10 | Per-car distribution (policy 2): rule 22 debits 3300 before the period is closed | **Approved as tenant option (D-40)**: on each sale, Dr 3310 Profit allocated in advance / Cr 3200 per partner; at close, 3310 is netted against 3300 | C-04, Q-10. **Implemented in Phase 7 (D-103)** |
| P-11 | VAT / tax on vehicle sales, consignment commission, invoices | **Decided (D-39): no tax rules.** Account 2500 is seeded but unused | G-08, Q-11, Q-06 |
| P-12 | Sale discount | Default: post the net price (sale price after discount) to 4100 and store the discount on the document only | Q-22. **Approved (Q-26); implemented in Phase 4** |
| P-13 | Late fees, early settlement discount (mode b), repossession, bad-debt write-off | Out of MVP scope until requested | G-12, G-13 |
| P-14 | Consigned-in car sold on installments / deferred: when the consignor's payable becomes due | No candidate | G-10, Q-15 |
| P-15 | Capital withdrawal (rule 2) and ownership % | No candidate. Percentages stay manual; withdrawal does not change % automatically | Q-19 |

---

## 6. Test matrix (SPEC §7, minimum)

| Test | Layer |
|---|---|
| Each rule 1–35: balances, correct accounts, correct subledger ids, correct amounts | pytest unit (pure functions) |
| Full scenario §4: every expected value above | pytest integration (real DB) |
| Trade-in: the sold car's profit is correct; the trade-in car's cost file starts at its agreed value | pytest integration |
| A bounced cheque restores the receivable and the bank balance | pytest integration |
| Reversal returns all balances to their prior state (snapshot of the trial balance before and after) | pytest integration |
| Posting into a locked period fails (also reversals dated in a locked period) | pgTAP + pytest |
| An unbalanced entry fails at the DB level even with a direct `post_journal_entry` call / raw insert attempt | pgTAP |
| Cross-tenant posting attempt fails (foreign account, foreign vehicle, wrong `app.tenant_id`) | pgTAP + pytest |
| `entry_no` gapless under 20 concurrent postings | pytest integration |
| Balance-sheet check (assets = liabilities + equity, including undistributed profit) on the seed data | CI |
