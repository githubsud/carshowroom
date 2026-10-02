/**
 * Money typed by people: Arabic phone keyboards produce Arabic-Indic digits
 * (٠١٢٣) and the Arabic decimal separator (٫). Normalise to a plain decimal
 * string ("25000.50") — still a string, never a JavaScript number (SPEC §3.3).
 */
import { AbstractControl, ValidationErrors } from '@angular/forms';

const DIGIT_MAP: Record<string, string> = {
  '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4', '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
  // Persian digits, common on some keyboards
  '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4', '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
};

const MONEY = /^\d{1,16}(\.\d{1,2})?$/;

export function normalizeMoneyInput(raw: string): string {
  return raw
    .trim()
    .replace(/[٠-٩۰-۹]/g, (digit) => DIGIT_MAP[digit])
    .replace(/٫/g, '.')
    // Thousands separators (Latin comma, Arabic thousands mark, spaces) are dropped.
    .replace(/[,٬\s]/g, '');
}

export function isValidMoney(value: string): boolean {
  return MONEY.test(value);
}

/** Positive amount with at most 2 decimals; the value is the normalised string. */
export function positiveMoney(control: AbstractControl<string | null>): ValidationErrors | null {
  const value = control.value ?? '';
  if (value === '') {
    return null; // leave "required" to Validators.required
  }
  if (!isValidMoney(value)) {
    return { money: true };
  }
  return /^0+(\.0+)?$/.test(value) ? { positive: true } : null;
}
