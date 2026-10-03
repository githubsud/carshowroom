# SayyaraDMS — Sharia compliance (الالتزام بأحكام الشريعة الإسلامية)

**Audience:** everyone who designs, builds, reviews or sells SayyaraDMS, including AI assistants working in this repository.
**Status:** **binding** (product owner, 2026-10-03; DECISIONS D-132). This file overrides any other document, default or request that conflicts with it.

> **The rule.** SayyaraDMS does not offer, compute, record or describe anything that contradicts Islamic Sharia (أحكام الشريعة الإسلامية). A feature that would do so is not built. If a request or an existing behaviour might conflict, it is stopped, recorded below under §5 as **SHARIA REVIEW**, and only built after the product owner confirms it, ideally with a qualified scholar.
>
> **القاعدة.** البرنامج لا يقدّم ولا يحسب ولا يسجّل ولا يصف أي شيء يخالف أحكام الشريعة الإسلامية. أي خاصية تخالفها لا تُبنى، وأي طلب أو سلوك فيه شبهة يتوقف ويُسجَّل للمراجعة الشرعية قبل تنفيذه.

This file states principles and how the app applies them. It is **not a fatwa**: points marked for review should be confirmed by a qualified scholar before the first real showroom goes live.

---

## 1. Principles

| # | Principle | What it means for the app |
|---|---|---|
| S-1 | **No riba (لا ربا).** No interest on any debt, loan or late payment | No interest rate, interest income or interest expense anywhere. No charge grows with time on money owed |
| S-2 | **A deferred-price sale is a sale, not a loan (بيع التقسيط / البيع بالأجل).** Selling a car for more on installments than for cash is permitted when the price is agreed once, at the contract | The installment price is fixed when the sale is posted and **never changes**: no increase for late payment, no rescheduling for a higher price. The difference is **sale profit**, never "interest" (فائدة) |
| S-3 | **No late penalties (لا غرامات تأخير)** that become income | No late fees. (A charity-pledge penalty, if ever wanted, needs scholar review and must never be the showroom's income) |
| S-4 | **Own before you sell (لا تبع ما ليس عندك).** | A car is sold only after its purchase is recorded (business rule 5). A consigned car is sold by the showroom **as the owner's agent**, never as its own |
| S-5 | **Partnership (الشركة):** profit by the agreed ratio; **loss by each partner's share of the capital** | See §5, item R-1 |
| S-6 | **Investment in a car (المضاربة / المشاركة):** the investor shares profit by an agreed ratio and bears loss of capital as Sharia allows; **no guaranteed return and no guaranteed capital** | Car-level investors are designed under this rule (§5, R-5) |
| S-7 | **Loans are interest-free (القرض الحسن).** | Loans to or from partners carry no interest field and repay exactly what was lent |
| S-8 | **No sale of debt at a discount (بيع الدين).** | No discounting of installment receivables or post-dated cheques, and no selling them to a third party |
| S-9 | **No gharar (الغرر):** the car, the price and the payment terms are known to both parties | Every sale states the car, the full price, and how and when it is paid |
| S-10 | **Wording matters.** | Arabic and English labels, documents, reports and messages never call a sale's gain "فائدة" or "interest" |

## 2. How the app applies them today

| Area | Behaviour | Principles |
|---|---|---|
| Installment sale at a higher price | Optional per showroom (Settings → Policies → ثمن البيع بالتقسيط). The **price difference (فرق سعر التقسيط)** is set once on the sale (an amount, or a percentage of the rest that is turned into a fixed amount), recorded as **sale profit** on 4300 "أرباح البيع بالتقسيط" on the sale date (D-130). The contract and invoice show **one total price** and state that it never increases with late payment | S-1, S-2, S-9, S-10 |
| Installments | Schedules are fixed at the sale. Payments only reduce what is owed; nothing is ever added to it | S-1, S-2 |
| Late payment | No late fees (Q-23, confirmed by the pilot) | S-3 |
| Bounced cheque | Bank charges are borne by the showroom by default; recharging the customer is optional and only for the **actual** charge (P-07) | S-1, S-3 |
| Deposit (عربون) | Refunded or kept in full, as agreed (D-72; the pilot refunds) | §5, R-3 |
| Selling a car | Only after its purchase is recorded; consigned cars as the owner's agent | S-4 |
| Discount | A reduction of the price agreed at the sale (D-124) | — |
| Partner loans | No interest; repayment never more than owed (D-63) | S-7 |
| Receivables and cheques | Never sold or discounted | S-8 |
| Subscription billing | Manual invoices; an unpaid subscription is suspended, never charged extra (D-116) | S-1, S-3 |

## 3. Wording (Arabic)

| Use | Do not use |
|---|---|
| فرق سعر التقسيط، ثمن البيع بالتقسيط، أرباح البيع بالتقسيط | فائدة، فوائد، سعر الفائدة، تمويل بفائدة |
| الثمن ثابت ولا يزيد بالتأخير | غرامة تأخير |
| قرض حسن / سلفة | قرض بفائدة |

## 4. Process

1. Every new feature, rule or text is checked against §1 before it is built. The check is part of the definition of done (code review and the DECISIONS entry).
2. Anything uncertain is recorded in §5 as **SHARIA REVIEW** and is not built until confirmed.
3. A qualified scholar reviews this file and §5 before the first real showroom goes live (Q-43).

## 5. Open points (SHARIA REVIEW)

| # | Point | Current behaviour | Proposed handling |
|---|---|---|---|
| R-1 | **Loss sharing between partners.** In a partnership, loss must follow each partner's share of the capital; profit may follow an agreed ratio | Profit and loss are both split by the ownership % entered for the partners (D-40, loss handling `ALLOCATE_TO_PARTNERS`). That % is set by hand and may differ from the capital each partner put in | **To fix before a showroom with partners goes live:** split losses by capital ratio (or require the ownership % to equal the capital ratio). Confirm with the owner and a scholar. The pilot showroom says it has no partners (Q-04, to confirm) |
| R-2 | **Pricing the installment difference by a percentage of the rest.** | The percentage is only a calculator: the result is a fixed amount agreed at the sale | Believed acceptable because the price is fixed once; confirm with a scholar |
| R-3 | **Keeping a deposit (بيع العربون)** when the buyer withdraws | Allowed as a full forfeit (D-72) | Accepted by the Hanbali school and widely by contemporary scholars; confirm. The pilot refunds in practice |
| R-4 | **Consignment at a net price** ("sell above X, keep the rest") | Supported (net-price terms, D-91) | Discussed by the scholars; many permit it when the net is known. Confirm |
| R-5 | **Car-level investors** (a trader funds one car) | Not built | Build only as mudaraba/musharaka: profit by agreed ratio, loss on capital per Sharia, no guaranteed return or capital. Terms awaited from the pilot owner |
| R-6 | **Bank interest received** on a showroom's bank account | No account for it | If it ever arises, record it apart (not as profit) for purification/charity; never in distributable profit. Confirm the treatment |
| R-7 | **Recharging bounced-cheque charges to the customer** | Optional, actual amount only (P-07) | Confirm that recovering the actual bank charge is acceptable |

## 6. Related decisions

D-130 (installment price difference recognised as sale profit at the sale), D-132 (this policy), D-40 (profit and loss sharing, see R-1), D-63 (partner loans), D-72 (deposits), D-91 (consignment terms), P-07 (bank charges), Q-23 (no late fees).
