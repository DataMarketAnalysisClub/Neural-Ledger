/**
 * Personal data removed from bank statements at import (ADR-028) comes back as stable codes in square brackets,
 * e.g. "Transf a [PERSON] [ID]". The backend never translates them: each known code becomes a chip labelled in the
 * user's language (`redaction.<CODE>` in i18n). Everything else stays plain text, never markup.
 */
import { Fragment } from "react";
import { EyeSlash } from "@phosphor-icons/react";
import type { RedactionPlaceholder } from "@/contracts/common/redaction";
import { tDynamic } from "@/i18n";

// Every code in the contract, exactly: a code added to or removed from the contract fails the build here.
const CODES: Record<RedactionPlaceholder, true> = { PERSON: true, ID: true, NUMBER: true, EMAIL: true, PHONE: true, ADDRESS: true };
export const PLACEHOLDERS = Object.keys(CODES) as RedactionPlaceholder[];

// One capture group, so String.split keeps the codes at the odd positions.
const PLACEHOLDER = new RegExp(`\\[(${PLACEHOLDERS.join("|")})\\]`);

export type RedactedPart = { text: string } | { code: RedactionPlaceholder };

/** "Transf a [PERSON]" → [{ text: "Transf a " }, { code: "PERSON" }]. Unknown or malformed codes stay text. */
export function splitPlaceholders(text: string): RedactedPart[] {
  return text
    .split(PLACEHOLDER)
    .map((part, i): RedactedPart => (i % 2 === 1 ? { code: part as RedactionPlaceholder } : { text: part }))
    .filter((part) => !("text" in part) || part.text !== "");
}

/** The same text for a plain-text attribute such as a tooltip: "Transf a [Name hidden]". */
export function redactedPlainText(text: string): string {
  return splitPlaceholders(text)
    .map((part) => ("code" in part ? `[${tDynamic("redaction", part.code)}]` : part.text))
    .join("");
}

/** Untrusted text with its placeholders rendered as translated chips. */
export function RedactedText({ text }: { text: string }) {
  return (
    <>
      {splitPlaceholders(text).map((part, i) => ("code" in part ? <PlaceholderChip key={i} code={part.code} /> : <Fragment key={i}>{part.text}</Fragment>))}
    </>
  );
}

function PlaceholderChip({ code }: { code: RedactionPlaceholder }) {
  return (
    <span
      data-placeholder={code}
      className="mx-0.5 inline-flex items-center gap-1 rounded-full bg-rail px-1.5 align-baseline text-xs font-medium whitespace-nowrap text-ink-2"
    >
      <EyeSlash aria-hidden weight="bold" className="size-3 shrink-0" />
      {tDynamic("redaction", code)}
    </span>
  );
}
