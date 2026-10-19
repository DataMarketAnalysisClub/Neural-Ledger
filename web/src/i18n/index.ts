import { en, type Messages } from "./en";

/** Registered locales. To add a language: create ./xx.ts exporting `Messages`, then register it here. */
const locales: Record<string, Messages> = { en };
export const locale = "en";
const messages: Messages = locales[locale] ?? en;

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
  return vars ? text.replace(/\{(\w+)\}/g, (_, name: string) => (name in vars ? String(vars[name]) : `{${name}}`)) : text;
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
