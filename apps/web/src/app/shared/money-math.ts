/**
 * Exact money arithmetic for forms (SPEC §3.3: no floating point). Amounts are
 * decimal strings with at most 2 decimals; the maths runs on integer cents.
 * Only for on-screen hints such as "remaining"; the API recomputes everything.
 */
import { isValidMoney } from './money-input';

export function toCents(value: string | null | undefined): bigint {
  if (!value || !isValidMoney(value)) {
    return 0n;
  }
  const [whole, fraction = ''] = value.split('.');
  return BigInt(whole) * 100n + BigInt((fraction + '00').slice(0, 2));
}

export function fromCents(cents: bigint): string {
  const sign = cents < 0n ? '-' : '';
  const abs = cents < 0n ? -cents : cents;
  return `${sign}${abs / 100n}.${(abs % 100n).toString().padStart(2, '0')}`;
}

/** total − every other amount, e.g. remaining = price − paid − deposit. */
export function moneyMinus(total: string | null | undefined, ...parts: (string | null | undefined)[]): string {
  return fromCents(parts.reduce((sum, part) => sum - toCents(part), toCents(total)));
}

export function moneySum(...parts: (string | null | undefined)[]): string {
  return fromCents(parts.reduce((sum, part) => sum + toCents(part), 0n));
}
