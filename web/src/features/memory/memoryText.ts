import { ApiError } from "@/api/client";
import type { MemoryView } from "@/api/hooks";
import { t } from "@/i18n";

/** The largest declared net salary (contracts/memory/memory_value.schema.json salary_net.amount.maximum). */
export const MAX_SALARY_NET = 100_000_000;

/** Why the API refused a memory write (memory_error), as the card and the profile tell it. */
export type MemoryProblem = "stale" | "used" | "consent" | "conflict" | "obsolete" | "invalid" | "other";

export function memoryProblem(error: unknown): MemoryProblem {
  if (!(error instanceof ApiError)) return "other";
  switch (error.detail.status) {
    case "PROPOSAL_STALE":
      return "stale";
    case "PROPOSAL_USED":
      return "used";
    case "CONSENT_REQUIRED":
      return "consent";
    case "VERSION_CONFLICT":
      return "conflict";
    case "INVALID_INPUT":
      return "invalid";
    default:
      return "other";
  }
}

/** A whole CLP amount the user typed ("1.200.000", "1200000"); null when it is not one the catalog takes. */
export function parseAmount(text: string): number | null {
  const digits = text.replace(/[.\s,$]/g, "").replace(/clp/i, "");
  if (!/^\d{1,9}$/.test(digits)) return null;
  const value = Number(digits);
  return value >= 1 && value <= MAX_SALARY_NET ? value : null;
}

/** Saved only, worded by what the statements say now: never "verified" unless the check says so. */
export function savedMessage(view: MemoryView): string {
  const status = view.items[0]?.check?.status ?? "declared";
  return t(`copilot.memory.saved.${status}`);
}
