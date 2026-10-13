/**
 * Display formatting only. The UI never computes money: these functions turn values the API
 * already computed into text. Amounts arrive as integers in minor units with an ISO currency
 * code; the only arithmetic here is shifting the decimal point for display.
 */

const MINUS = "−"; // a real minus sign, not a hyphen

const fractionDigitsCache = new Map<string, number>();
function fractionDigits(currency: string): number {
  let digits = fractionDigitsCache.get(currency);
  if (digits === undefined) {
    try {
      digits = new Intl.NumberFormat("en", { style: "currency", currency }).resolvedOptions().maximumFractionDigits ?? 0;
    } catch {
      digits = 0;
    }
    fractionDigitsCache.set(currency, digits);
  }
  return digits;
}

/** `CLP 1,500,000`, `CLP −18,995`, `USD 12.50`. The ISO code is always shown, never a bare symbol. */
export function formatMoney(minorUnits: number, currency: string, opts: { signed?: boolean } = {}): string {
  const digits = fractionDigits(currency);
  const major = Math.abs(minorUnits) / 10 ** digits;
  const body = new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(major);
  const sign = minorUnits < 0 ? MINUS : opts.signed && minorUnits > 0 ? "+" : "";
  return `${currency} ${sign}${body}`;
}

/** The number alone, for table cells whose column header already carries the currency. */
export function formatAmount(minorUnits: number, currency: string, opts: { signed?: boolean } = {}): string {
  return formatMoney(minorUnits, currency, opts).slice(currency.length + 1);
}

/** A ratio from the API (0.219444) as a percentage (21.9%). */
export function formatPercent(ratio: number, digits = 1): string {
  const value = new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Math.abs(ratio) * 100);
  return `${ratio < 0 ? MINUS : ""}${value}%`;
}

export function formatNumber(value: number, digits = 2): string {
  const body = new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(Math.abs(value));
  return `${value < 0 ? MINUS : ""}${body}`;
}

/** "2026-12" -> "Dec 2026". Always with the year: "Dec 26" is ambiguous. */
export function formatMonth(month: string, style: "short" | "long" = "short"): string {
  const [y, m] = month.split("-").map(Number);
  if (!y || !m) return month;
  return new Intl.DateTimeFormat("en-US", { month: style, year: "numeric", timeZone: "UTC" }).format(Date.UTC(y, m - 1, 1));
}

/** "2027-01-01" -> "Jan 1, 2027". */
export function formatDate(iso: string): string {
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: iso.length === 10 ? "UTC" : undefined }).format(d);
}

/** "a1f3c9...9c" style truncation for hashes and ids shown in mono. */
export function shortHash(hash: string, head = 6, tail = 4): string {
  return hash.length <= head + tail + 1 ? hash : `${hash.slice(0, head)}…${hash.slice(-tail)}`;
}

/** Words for screen readers where the visual uses a sign: "minus CLP 18,995". */
export function moneyForSpeech(minorUnits: number, currency: string): string {
  const text = formatMoney(Math.abs(minorUnits), currency);
  return minorUnits < 0 ? `minus ${text}` : text;
}
