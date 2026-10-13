/**
 * The confirmation contract made visible. One receipt changes state from Proposal to Confirmed to
 * Created; terms are read-only and are sent back exactly as received. Execution is a separate step.
 * Nothing changes on screen until the API answers.
 */
import { useEffect, useId, useRef, type ReactNode } from "react";
import { Check, LockSimple, Prohibit, SealCheck } from "@phosphor-icons/react";
import type { ActionOutcome, ActionTerms } from "@/api/client";
import { useCountdown } from "@/lib/expiry";
import { formatDate, formatMoney, moneyForSpeech, shortHash } from "@/lib/format";
import { shouldAnimate } from "@/lib/motion";
import { t, tDynamic } from "@/i18n";
import { Button, Notice, cn, describeError } from "./ui";

type Proposal = NonNullable<ActionOutcome["proposal"]>;
type Authorization = NonNullable<ActionOutcome["authorization"]>;
type Receipt = NonNullable<ActionOutcome["receipt"]>;

// ---- Verdict banner ------------------------------------------------------------------------------

/** A refusal is a feature: its own component, not a generic alert. */
export function VerdictBanner({
  reason,
  currency,
  authorized,
  requested,
  detail,
  compact,
}: {
  reason: string | null | undefined;
  currency: string;
  authorized?: number | null;
  requested?: number | null;
  detail?: ReactNode;
  compact?: boolean;
}) {
  const hasAmounts = typeof authorized === "number" && typeof requested === "number";
  // Several banners can be on screen at once (chat and receipt), so the label id must be unique.
  const titleId = useId();
  // Inline (compact) banners sit inside another section, so they take the next heading level.
  const Heading = compact ? "h3" : "h2";
  return (
    <section
      role="alert"
      aria-labelledby={titleId}
      className={cn("rounded-control border border-danger/40 bg-danger-bg", compact ? "p-4" : "p-6")}
    >
      <div className="flex items-start gap-3">
        <Prohibit aria-hidden weight="bold" className={cn("shrink-0 text-danger", compact ? "mt-0.5 size-5" : "size-7")} />
        <div className="min-w-0 flex-1">
          <Heading id={titleId} className={cn("font-semibold text-danger", compact ? "text-sm" : "text-lg")}>
            {t("blocked.title")}: {tDynamic("blocked.reasons", reason, "blocked.reasons.UNKNOWN")}
          </Heading>
          {hasAmounts && (
            <dl className={cn("mt-4 grid max-w-md grid-cols-2 gap-4", compact && "mt-3")}>
              <div>
                <dt className="text-xs text-ink-2">{t("blocked.requested")}</dt>
                <dd className={cn("num font-semibold text-ink line-through decoration-danger decoration-2", compact ? "text-base" : "text-xl")}>
                  <span className="sr-only">{moneyForSpeech(requested, currency)}</span>
                  <span aria-hidden>{formatMoney(requested, currency)}</span>
                </dd>
              </div>
              <div>
                <dt className="text-xs text-ink-2">{t("blocked.authorized")}</dt>
                <dd className={cn("num font-semibold text-ink", compact ? "text-base" : "text-xl")}>{formatMoney(authorized, currency)}</dd>
              </div>
            </dl>
          )}
          <p className="mt-3 text-sm text-ink">{t("blocked.nothingChanged")}</p>
          <p className="mt-2 text-xs text-ink-2">
            {t("blocked.code")} <span className="font-mono">{reason ?? "UNKNOWN"}</span>
          </p>
          {detail}
        </div>
      </div>
    </section>
  );
}

// ---- Stepper -------------------------------------------------------------------------------------

type Stage = "pending" | "confirmed" | "executed";
const STEPS: { id: Stage; label: Parameters<typeof t>[0] }[] = [
  { id: "pending", label: "receipt.steps.review" },
  { id: "confirmed", label: "receipt.steps.confirm" },
  { id: "executed", label: "receipt.steps.execute" },
];

function Stepper({ stage }: { stage: Stage }) {
  // Step i is done once the stage has moved past it; the current step is the next action.
  const order: Record<Stage, number> = { pending: 1, confirmed: 2, executed: 3 };
  const reached = order[stage];
  return (
    <ol className="grid grid-cols-3 gap-2" aria-label={t("receipt.title")}>
      {STEPS.map((step, i) => {
        const done = i < reached || (stage === "executed" && i === 2);
        const current = !done && i === reached;
        return (
          <li key={step.id} aria-current={current ? "step" : undefined} className="min-w-0">
            <div className={cn("h-1 rounded-full transition-colors duration-200", done ? "bg-ink" : current ? "bg-accent" : "bg-line")} />
            <p className={cn("mt-2 flex items-center gap-1.5 text-xs", done ? "text-ink" : current ? "font-semibold text-accent" : "text-ink-3")}>
              {done && <Check aria-hidden weight="bold" className="size-3.5" />}
              {t(step.label)}
              <span className="sr-only">, {t(done ? "receipt.stepState.done" : current ? "receipt.stepState.current" : "receipt.stepState.upcoming")}</span>
            </p>
          </li>
        );
      })}
    </ol>
  );
}

// ---- Terms ---------------------------------------------------------------------------------------

function TermRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-6 border-b border-line py-1.5 last:border-0">
      <dt className="text-sm text-ink-2">{label}</dt>
      <dd className="text-right text-sm font-medium text-ink">{children}</dd>
    </div>
  );
}

function Terms({ terms }: { terms: ActionTerms }) {
  return (
    <div>
      <p className="mb-1 flex items-center gap-1.5 text-xs text-ink-3">
        <LockSimple aria-hidden weight="bold" className="size-3.5" />
        {t("receipt.terms.label")}
      </p>
      <dl>
        <TermRow label={t("receipt.terms.action")}>{tDynamic("receipt.terms.actions", terms.action)}</TermRow>
        <TermRow label={t("receipt.terms.amount")}>
          <span className="num">{formatMoney(terms.amount, terms.currency)}</span>
        </TermRow>
        <TermRow label={t("receipt.terms.frequency")}>{tDynamic("receipt.terms.frequencies", terms.frequency)}</TermRow>
        <TermRow label={t("receipt.terms.source")}>{tDynamic("receipt.terms.accounts", terms.source_account)}</TermRow>
        <TermRow label={t("receipt.terms.destination")}>{tDynamic("receipt.terms.accounts", terms.destination)}</TermRow>
        <TermRow label={t("receipt.terms.effective")}>{formatDate(terms.effective_date)}</TermRow>
      </dl>
    </div>
  );
}

// ---- Validity --------------------------------------------------------------------------------------

function Validity({ expiresAt, kind }: { expiresAt: string; kind: "proposal" | "authorization" }) {
  const countdown = useCountdown(expiresAt);
  if (!countdown) return null;
  const announce =
    countdown.threshold === "expired" ? t("receipt.validity.expired") : countdown.threshold ? t(`receipt.validity.${kind}`, { time: countdown.label }) : "";
  return (
    <div className="text-xs">
      <p role="timer" aria-live="off" className={cn("num font-medium", countdown.expired ? "text-danger" : countdown.threshold ? "text-warning" : "text-ink-2")}>
        {countdown.expired ? t("receipt.status.expired") : t(`receipt.validity.${kind}`, { time: countdown.label })}
      </p>
      <p className="sr-only" aria-live="polite">
        {announce}
      </p>
      {kind === "proposal" && <p className="mt-1 text-ink-3">{t("receipt.validity.explain")}</p>}
    </div>
  );
}

// ---- Receipt -----------------------------------------------------------------------------------------

export interface ReceiptProps {
  proposal?: Proposal | null;
  authorization?: Authorization | null;
  receipt?: Receipt | null;
  onConfirm: (proposal: Proposal) => void;
  onExecute: (authorization: Authorization) => void;
  confirming: boolean;
  executing: boolean;
  error?: unknown;
  blocked?: ActionOutcome | null;
  onBack?: () => void;
}

export function ProposalReceipt({ proposal, authorization, receipt, onConfirm, onExecute, confirming, executing, error, blocked, onBack }: ReceiptProps) {
  const stage: Stage | null = receipt?.ok ? "executed" : authorization && !authorization.used ? "confirmed" : proposal ? "pending" : null;
  const headingRef = useRef<HTMLHeadingElement>(null);
  const terms = (authorization?.terms ?? proposal?.terms) as ActionTerms | undefined;
  const proposalCountdown = useCountdown(stage === "pending" ? proposal?.expires_at : null);
  const authCountdown = useCountdown(stage === "confirmed" ? authorization?.expires_at : null);
  const expired = (stage === "pending" && proposalCountdown?.expired) || (stage === "confirmed" && authCountdown?.expired);

  // Move focus to the receipt when it appears or changes state, so keyboard and screen reader users follow it.
  useEffect(() => {
    if (stage) headingRef.current?.focus();
  }, [stage]);

  if (!stage || !terms) {
    return (
      <div className="rounded-control border border-dashed border-control/60 p-6">
        <p className="text-base font-medium text-ink">{t("receipt.title")}</p>
        <p className="mt-2 text-sm text-ink-2">{t("receipt.empty")}</p>
      </div>
    );
  }

  const amount = formatMoney(terms.amount, terms.currency);
  const frequency = tDynamic("receipt.terms.frequencies", terms.frequency).toLowerCase();

  return (
    <article aria-labelledby="receipt-title" className={cn("rounded-object border bg-surface p-6 transition-shadow duration-200", stage === "pending" ? "border-line" : "border-ink/20 shadow-object")}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 id="receipt-title" ref={headingRef} tabIndex={-1} className="text-lg font-semibold text-ink outline-none">
            {t("receipt.title")}
          </h2>
          <p className="mt-0.5 text-sm text-ink-2" role="status">
            {expired ? t("receipt.status.expired") : t(`receipt.status.${stage}`)}
          </p>
        </div>
        {stage !== "pending" && (
          <span
            aria-hidden
            className={cn(
              "grid size-11 shrink-0 place-items-center rounded-full border-2",
              stage === "executed" ? "border-positive text-positive" : "border-ink text-ink",
              shouldAnimate() && "animate-[seal_200ms_var(--ease-out)]",
            )}
          >
            <SealCheck weight="bold" className="size-6" />
          </span>
        )}
      </div>

      <div className="mt-5">
        <Stepper stage={stage} />
      </div>

      <p className="num mt-5 text-2xl font-semibold tracking-[-0.02em] text-ink">
        {amount} <span className="text-base font-normal text-ink-2">{frequency}</span>
      </p>

      <div className="mt-4">
        <Terms terms={terms} />
      </div>

      {proposal?.source_snapshot_id && (
        <p className="mt-3 text-xs text-ink-3">
          {t("receipt.terms.fromPlan", { snapshot: "" })}
          <span className="font-mono">{shortHash(proposal.source_snapshot_id, 10, 6)}</span>
        </p>
      )}

      <div className="mt-5">
        {stage === "pending" && proposal && <Validity kind="proposal" expiresAt={proposal.expires_at} />}
        {stage === "confirmed" && authorization && <Validity kind="authorization" expiresAt={authorization.expires_at} />}
      </div>

      {blocked && (
        <div className="mt-5">
          <VerdictBanner compact reason={blocked.reason} currency={terms.currency} authorized={blocked.authorized_amount} requested={blocked.requested_amount} />
        </div>
      )}
      {error && !blocked ? (
        <div className="mt-5">
          <Notice tone="danger" title={describeError(error)} />
        </div>
      ) : null}

      <div className="mt-6 space-y-3">
        {stage === "pending" && proposal && (
          <>
            <Button
              variant="money"
              size="lg"
              className="w-full"
              disabled={confirming || !!expired}
              busy={confirming}
              onClick={() => onConfirm(proposal)}
              aria-label={t("receipt.confirm", { amount: moneyForSpeech(terms.amount, terms.currency), frequency })}
            >
              {confirming ? t("receipt.confirming") : t("receipt.confirm", { amount, frequency })}
            </Button>
            <p className="text-xs text-ink-2">{t("receipt.confirmNote")}</p>
            {onBack && (
              <Button variant="quiet" size="sm" onClick={onBack}>
                {t("receipt.back")}
              </Button>
            )}
          </>
        )}
        {stage === "confirmed" && authorization && (
          <>
            <p className="text-sm text-ink">{t("receipt.confirmed")}</p>
            <Button
              variant="money"
              size="lg"
              className="w-full"
              disabled={executing || !!expired}
              busy={executing}
              onClick={() => onExecute(authorization)}
              aria-label={t("receipt.execute", { amount: moneyForSpeech(terms.amount, terms.currency) })}
            >
              {executing ? t("receipt.executing") : t("receipt.execute", { amount })}
            </Button>
            <p className="text-xs text-ink-2">{t("receipt.executeNote")}</p>
          </>
        )}
        {stage === "executed" && receipt && (
          <Notice tone="positive" title={t("receipt.executed", { reference: receipt.reference ?? "" })} />
        )}
        {expired && <p className="text-sm text-danger">{t("receipt.validity.expired")}</p>}
      </div>
    </article>
  );
}
