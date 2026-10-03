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

/**
 * Split an amount by percentage weights ("60.0000"), in cents, adding up exactly:
 * the leftover cents go to the largest remainders (a suggestion the user can edit).
 */
export function splitByWeights(total: string, weights: readonly string[]): string[] {
  const cents = toCents(total);
  const scaled = weights.map((w) => BigInt(Math.round(Number(w) * 10_000)));
  const sum = scaled.reduce((a, b) => a + b, 0n);
  if (sum === 0n) {
    return weights.map(() => '0.00');
  }
  const shares = scaled.map((w) => (cents * w) / sum);
  const remainders = scaled.map((w, i) => ({ i, r: cents * w - shares[i] * sum }));
  let left = cents - shares.reduce((a, b) => a + b, 0n);
  for (const { i } of remainders.sort((a, b) => (b.r > a.r ? 1 : b.r < a.r ? -1 : a.i - b.i))) {
    if (left <= 0n) {
      break;
    }
    shares[i] += 1n;
    left -= 1n;
  }
  return shares.map(fromCents);
}
