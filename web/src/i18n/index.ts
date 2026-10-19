import { en, type Messages } from "./en";
import { es } from "./es";
import { zh } from "./zh";

/**
 * Registered locales, each named in its own language for the picker. To add a language: create ./xx.ts
 * exporting `Messages`, then register it here and in DATE_LOCALES.
 */
export const LOCALES = { en: "English", es: "Español", zh: "中文" } as const;
export type Locale = keyof typeof LOCALES;
const locales: Record<Locale, Messages> = { en, es, zh };
/** Dates follow the language. Numbers do not: money reads `CLP 1,500,000` in every language (lib/format). */
const DATE_LOCALES: Record<Locale, string> = { en: "en-US", es: "es-CL", zh: "zh-CN" };
const STORAGE_KEY = "nl.locale";

function storedLocale(): Locale {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved && saved in locales ? (saved as Locale) : "en";
  } catch {
    return "en"; // storage blocked: the default language still works
  }
}

export const locale: Locale = storedLocale();
export const dateLocale = DATE_LOCALES[locale];
const messages: Messages = locales[locale];
if (typeof document !== "undefined") document.documentElement.lang = locale;

/**
 * shortcut: switching reloads the page, because t() reads the language once at load. Make the messages
 * reactive if losing unsaved input (a copilot draft, a form) on a switch ever matters.
 */
export function setLocale(next: Locale): void {
  if (next === locale) return;
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    return; // nowhere to keep the choice: a reload would only bring the old language back
  }
  window.location.reload();
}

type Leaves<T, P extends string = ""> = T extends string
  ? P
  : T extends readonly unknown[]
    ? never
    : { [K in keyof T & string]: Leaves<T[K], P extends "" ? K : `${P}.${K}`> }[keyof T & string];

export type MessageKey = Leaves<typeof en>;
type Vars = Record<string, string | number>;

function lookup(path: string): unknown {
  return path.split(".").reduce<unknown>((node, part) => (node && typeof node === "object" ? (node as Record<string, unknown>)[part] : undefined), messages);
}

/** Translate a key, filling {placeholders}. Missing keys render the key itself so gaps are visible. */
export function t(key: MessageKey, vars?: Vars): string {
  const raw = lookup(key);
  const text = typeof raw === "string" ? raw : key;
  if (!vars) return text;
  const filled = text.replace(/\{(\w+)\}/g, (_, name: string) => (name in vars ? String(vars[name]) : `{${name}}`));
  // A sentence that opens with a value still starts with a capital: Spanish months are lowercase ("diciembre de 2026").
  return text.startsWith("{") ? filled.charAt(0).toLocaleUpperCase(locale) + filled.slice(1) : filled;
}

/** Translate a dynamic key from the API (a block reason, an event kind). Falls back when unknown. */
export function tDynamic(prefix: string, code: string | null | undefined, fallback?: MessageKey): string {
  const raw = code ? lookup(`${prefix}.${code}`) : undefined;
  if (typeof raw === "string") return raw;
  return fallback ? t(fallback) : (code ?? "");
}

export function tList(key: "copilot.prompts" | "auth.hero.features"): readonly string[] {
  const raw = lookup(key);
  return Array.isArray(raw) ? (raw as string[]) : [];
}
