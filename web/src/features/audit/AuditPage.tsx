import { useMemo, useState } from "react";
import { CheckCircle, LinkSimple, LinkBreak, Prohibit } from "@phosphor-icons/react";
import { useAudit, useFinancialState, usePersona, useVerifyChain } from "@/api/hooks";
import type { AuditEvent } from "@/api/client";
import { VerdictBanner } from "@/components/actions";
import { Button, EmptyState, ErrorState, Loading, Notice, PageHeader, Section, cn } from "@/components/ui";
import { formatDate, shortHash } from "@/lib/format";
import { t, tDynamic } from "@/i18n";

type Filter = "all" | "actions" | "blocked";
type Scope = "all" | "session";
const selectClass =
  "h-9 rounded-control border border-control bg-surface px-2 text-sm text-ink focus:outline-none focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25";
const ACTION_KINDS = new Set(["PROPOSAL_CREATED", "ACTION_CONFIRMED", "EXECUTION_STARTED", "ACTION_EXECUTED", "ACTION_FAILED", "ACTION_BLOCKED"]);

/** The audit detail of a mismatch reads "AUTHORIZED: 100000 REQUESTED: 700000"; read it for display only. */
function amountsFrom(detail: string | null | undefined): { authorized: number; requested: number } | null {
  const match = detail?.match(/AUTHORIZED:\s*(-?\d+)\s+REQUESTED:\s*(-?\d+)/);
  return match ? { authorized: Number(match[1]), requested: Number(match[2]) } : null;
}

function isBlocked(e: AuditEvent) {
  return e.kind === "ACTION_BLOCKED" || e.kind === "INJECTION_FLAGGED";
}

export function AuditPage() {
  const { sessionId } = usePersona();
  const [scope, setScope] = useState<Scope>("all");
  const audit = useAudit(scope === "session" ? sessionId : undefined);
  const state = useFinancialState();
  const verify = useVerifyChain();
  const [filter, setFilter] = useState<Filter>("all");
  const currency = state.data?.data?.currency ?? "CLP";

  const events = useMemo(() => [...(audit.data?.events ?? [])].sort((a, b) => b.sequence - a.sequence), [audit.data]);
  const latestBlock = events.find((e) => e.kind === "ACTION_BLOCKED");
  const shown = events.filter((e) => (filter === "all" ? true : filter === "actions" ? ACTION_KINDS.has(e.kind) : isBlocked(e)));

  if (audit.isError) return <ErrorState error={audit.error} onRetry={() => void audit.refetch()} />;
  if (audit.isPending) return <Loading className="max-w-5xl" />;

  const amounts = amountsFrom(latestBlock?.detail);

  return (
    <>
      <PageHeader
        title={t("audit.title")}
        subtitle={t("audit.subtitle")}
        actions={
          <Button variant="primary" onClick={() => verify.mutate()} busy={verify.isPending} disabled={verify.isPending}>
            <LinkSimple aria-hidden className="size-4" />
            {verify.isPending ? t("audit.verifying") : t("audit.verify")}
          </Button>
        }
      />

      <div aria-live="polite" className="mb-8 empty:hidden">
        {verify.data &&
          (verify.data.ok ? (
            <Notice tone="positive" icon={CheckCircle} title={t("audit.chainOk", { count: verify.data.checked })} />
          ) : (
            <Notice tone="danger" icon={LinkBreak} title={t("audit.chainBroken", { sequence: verify.data.broken_at ?? "?" })}>
              {verify.data.reason}
            </Notice>
          ))}
        {verify.isError && <ErrorState error={verify.error} />}
      </div>

      <Section id="latest-block" title={t("audit.latestBlock")} className="mb-12">
        {latestBlock ? (
          <VerdictBanner
            reason={latestBlock.blocked_reason}
            currency={currency}
            authorized={amounts?.authorized}
            requested={amounts?.requested}
            detail={
              <p className="mt-2 text-xs text-ink-2">
                {t("audit.columns.sequence")} <span className="num font-mono">{latestBlock.sequence}</span>
                <span aria-hidden> · </span>
                {t(`audit.actors.${latestBlock.actor}`)}
                {latestBlock.permission_tier && (
                  <>
                    <span aria-hidden> · </span>
                    {tDynamic("audit.tiers", latestBlock.permission_tier)}
                  </>
                )}
              </p>
            }
          />
        ) : (
          <p className="text-sm text-ink-2">{t("audit.noBlocks")}</p>
        )}
      </Section>

      <Section
        id="chain"
        title={t("nav.audit")}
        aside={
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2 text-sm text-ink-2">
              {t("audit.scope")}
              <select value={scope} onChange={(e) => setScope(e.target.value as Scope)} className={selectClass}>
                {(["all", "session"] as const).map((s) => (
                  <option key={s} value={s}>
                    {t(`audit.scopes.${s}`)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm text-ink-2">
              {t("audit.filter")}
              <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)} className={selectClass}>
                {(["all", "actions", "blocked"] as const).map((f) => (
                  <option key={f} value={f}>
                    {t(`audit.filters.${f}`)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        }
      >
        {shown.length === 0 ? (
          <EmptyState title={t("audit.empty")} />
        ) : (
          // A fixed-height box that scrolls on its own; focusable so the keyboard can scroll it too.
          <div
            role="region"
            aria-label={t("audit.scrollBox")}
            tabIndex={0}
            className="max-h-[min(70vh,640px)] overflow-auto rounded-control border border-line bg-surface"
          >
            <table className="w-full min-w-[760px] text-sm">
              <caption className="sr-only">{t("nav.audit")}</caption>
              <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_var(--color-line)]">
                <tr className="border-b border-line text-left text-xs text-ink-3">
                  <th scope="col" className="w-16 px-5 py-3 font-medium">
                    {t("audit.columns.sequence")}
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium">
                    {t("audit.columns.event")}
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium">
                    {t("audit.columns.actor")}
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium">
                    {t("audit.columns.tier")}
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium">
                    {t("audit.columns.result")}
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium">
                    {t("audit.columns.hash")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((e) => {
                  const blocked = isBlocked(e);
                  const broken = verify.data && !verify.data.ok && verify.data.broken_at === e.sequence;
                  return (
                    <tr key={e.event_id} className={cn("border-b border-line last:border-0", (blocked || broken) && "bg-danger-bg/60")}>
                      <td className="num px-5 py-3 font-mono text-xs text-ink-2">{e.sequence}</td>
                      <th scope="row" className="px-5 py-3 text-left font-normal">
                        <span className={cn("inline-flex items-center gap-1.5", blocked ? "font-medium text-danger" : "text-ink")}>
                          {blocked && <Prohibit aria-hidden weight="bold" className="size-4" />}
                          {tDynamic("audit.kinds", e.kind)}
                        </span>
                        <span className="mt-0.5 block text-xs text-ink-3">
                          {e.tool_requested ? <span className="font-mono">{e.tool_requested}</span> : null}
                          {e.tool_requested ? <span aria-hidden> · </span> : null}
                          {formatDate(e.timestamp)}
                        </span>
                      </th>
                      <td className="px-5 py-3 text-ink-2">{t(`audit.actors.${e.actor}`)}</td>
                      <td className="px-5 py-3 text-ink-2">{e.permission_tier ? tDynamic("audit.tiers", e.permission_tier) : ""}</td>
                      <td className="px-5 py-3">
                        {e.blocked_reason ? (
                          <span className="font-mono text-xs text-danger">{e.blocked_reason}</span>
                        ) : (
                          <span className="font-mono text-xs text-ink-2">{e.execution_result ?? ""}</span>
                        )}
                      </td>
                      <td className="px-5 py-3">
                        <span className="flex flex-col font-mono text-xs leading-5">
                          <span className="text-ink-3" title={`${t("audit.prevHash")}: ${e.prev_hash}`}>
                            <span className="sr-only">{t("audit.prevHash")}: </span>
                            {shortHash(e.prev_hash)}
                          </span>
                          <span className="text-ink" title={`${t("audit.eventHash")}: ${e.event_hash}`}>
                            <span className="sr-only">{t("audit.eventHash")}: </span>
                            {shortHash(e.event_hash)}
                          </span>
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </>
  );
}
