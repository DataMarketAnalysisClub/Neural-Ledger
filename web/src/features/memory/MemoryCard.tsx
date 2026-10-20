import { useState } from "react";
import { CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { useConfirmMemory, useMemoryConsent, useMemoryCounters, type IncomeProposal } from "@/api/hooks";
import type { ChatReply } from "@/api/client";
import { Button, ErrorState, cn } from "@/components/ui";
import { t } from "@/i18n";
import { formatMoney } from "@/lib/format";
import { isObsolete } from "./counters";
import { memoryProblem, parseAmount, savedMessage, type MemoryProblem } from "./memoryText";

type Dependency = NonNullable<ChatReply["memory_dependency"]>;

/**
 * A net salary the copilot read from the user's message (ADR-048). The user selects or types the amount, checks the
 * pay month and confirms; nothing is saved before, and saving moves no money and changes no projection. The card is
 * memory's own: it reuses the look of a confirmation, not the banking authorization or its execution.
 * It is obsolete once the memory counters it was prepared under move (a revocation, another confirmation, a deletion),
 * and every refusal from the API (409, 428) closes it with the reason; it never sends twice.
 */
export function MemoryCard({ proposal, dependency, currency }: { proposal: IncomeProposal; dependency?: Dependency | null; currency: string }) {
  const confirm = useConfirmMemory();
  useMemoryConsent(); // keeps the counters current: a revocation in another tab closes the card when it is read
  const known = useMemoryCounters();
  const [choice, setChoice] = useState<string>(proposal.status === "READY" ? String(proposal.candidates[0]) : "");
  const [typed, setTyped] = useState("");
  const [month, setMonth] = useState(proposal.effective_from.pay_month);
  const [baseAmount, setBaseAmount] = useState("");
  const [baseMonth, setBaseMonth] = useState("");
  const [attempted, setAttempted] = useState(false);

  const askAmount = proposal.status === "ASK_AMOUNT" || choice === "other";
  const amount = askAmount ? parseAmount(typed) : parseAmount(choice);
  const base = proposal.needs_base && (baseAmount || baseMonth) ? { amount: parseAmount(baseAmount), month: baseMonth } : null;
  const baseValid = !base || (base.amount !== null && /^\d{4}-\d{2}$/.test(base.month) && base.month < month);

  const moved = isObsolete(dependency, known);
  const problem: MemoryProblem | null = confirm.isError ? memoryProblem(confirm.error) : null;
  const saved = confirm.isSuccess ? confirm.data : null;
  const closed: MemoryProblem | null = saved ? null : problem && problem !== "invalid" && problem !== "other" ? problem : moved ? "obsolete" : null;

  return (
    <form
      className="mt-3 rounded-control border border-accent/30 bg-surface p-4 text-sm"
      aria-label={t("copilot.memory.title")}
      onSubmit={(e) => {
        e.preventDefault();
        setAttempted(true);
        if (amount === null || !baseValid || confirm.isPending || saved || closed) return;
        confirm.mutate({
          proposalId: proposal.proposal_id,
          salary_net: { amount, net: true, effective_from: month },
          expected_version: proposal.expected_version,
          ...(base && base.amount !== null ? { base: { amount: base.amount, net: true, effective_from: base.month } } : {}),
        });
      }}
    >
      <p className="text-xs font-medium text-ink-3">{t("copilot.memory.title")}</p>
      {saved ? (
        <p role="status" className="mt-2 flex items-start gap-1.5 font-medium text-positive">
          <CheckCircle aria-hidden weight="fill" className="mt-0.5 size-4 shrink-0" />
          {savedMessage(saved)}
        </p>
      ) : closed ? (
        <p role="status" className="mt-2 flex items-start gap-1.5 text-warning">
          <WarningCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
          {t(`copilot.memory.${closed}`)}
        </p>
      ) : (
        <>
          {proposal.status === "CHOOSE_AMOUNT" && (
            <fieldset className="mt-2">
              <legend className="text-xs font-medium text-ink-2">{t("copilot.memory.choose")}</legend>
              <div className="mt-1 flex flex-wrap gap-2">
                {[...proposal.candidates.map(String), "other"].map((value) => (
                  <label
                    key={value}
                    className={cn(
                      "cursor-pointer rounded-full border px-3 py-1.5 text-sm has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent",
                      choice === value ? "border-accent bg-accent-soft font-medium text-ink" : "border-line text-ink-2",
                    )}
                  >
                    <input type="radio" name={`salary-${proposal.proposal_id}`} value={value} checked={choice === value} onChange={() => setChoice(value)} className="sr-only" />
                    {value === "other" ? t("copilot.memory.other") : formatMoney(Number(value), currency)}
                  </label>
                ))}
              </div>
            </fieldset>
          )}
          {proposal.status === "READY" && <p className="mt-1 text-xl font-semibold text-ink">{formatMoney(proposal.candidates[0]!, currency)}</p>}
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {askAmount && (
              <label className="text-xs text-ink-2">
                {t("copilot.memory.amount")}
                <input
                  inputMode="numeric"
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  className="mt-1 block h-10 w-full rounded-control border border-control bg-surface px-2 text-sm text-ink"
                />
              </label>
            )}
            <label className="text-xs text-ink-2">
              {t("copilot.memory.month")}
              <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className="mt-1 block h-10 w-full rounded-control border border-control bg-surface px-2 text-sm text-ink" />
              <span className="mt-1 block text-ink-3">{t(`copilot.memory.readAs.${proposal.effective_from.read_as}`)}</span>
            </label>
          </div>
          {proposal.needs_base && (
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <label className="text-xs text-ink-2">
                {t("copilot.memory.base")}
                <input inputMode="numeric" value={baseAmount} onChange={(e) => setBaseAmount(e.target.value)} className="mt-1 block h-10 w-full rounded-control border border-control bg-surface px-2 text-sm text-ink" />
              </label>
              <label className="text-xs text-ink-2">
                {t("copilot.memory.baseMonth")}
                <input type="month" value={baseMonth} onChange={(e) => setBaseMonth(e.target.value)} className="mt-1 block h-10 w-full rounded-control border border-control bg-surface px-2 text-sm text-ink" />
              </label>
              <p className="text-xs text-ink-3 sm:col-span-2">{t("copilot.memory.baseHint")}</p>
            </div>
          )}
          {attempted && (amount === null || !baseValid) && (
            <p role="alert" className="mt-2 text-xs text-warning">
              {t("copilot.memory.invalidAmount")}
            </p>
          )}
          {problem && (problem === "invalid" || problem === "other") && (
            <div className="mt-2">
              <ErrorState error={confirm.error} />
            </div>
          )}
          <Button type="submit" size="sm" variant="primary" className="mt-3" busy={confirm.isPending} disabled={confirm.isPending}>
            {t("copilot.memory.confirm")}
          </Button>
          <p className="mt-2 text-xs text-ink-3">{t("copilot.memory.savedOnly")}</p>
        </>
      )}
    </form>
  );
}
