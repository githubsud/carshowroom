import { HttpParams } from '@angular/common/http';

export type Query = Record<string, string | number | boolean | readonly string[] | null | undefined>;

/** Query parameters without empty values; arrays become repeated keys (?status=A&status=B). */
export function toParams(query: Query): HttpParams {
  let result = new HttpParams();
  for (const [key, value] of Object.entries(query)) {
    if (Array.isArray(value)) {
      for (const item of value) {
        result = result.append(key, item);
      }
    } else if (value !== null && value !== undefined && value !== '') {
      result = result.set(key, String(value));
    }
  }
  return result;
}

export function idempotent(key: string): { headers: Record<string, string> } {
  return { headers: { 'Idempotency-Key': key } };
}
