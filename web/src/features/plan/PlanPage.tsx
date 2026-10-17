import { Link } from "react-router-dom";
import { ArrowRight, Prohibit, Warning } from "@phosphor-icons/react";
import { useCapacity, useFinancialState, usePermittedProfile, usePersona, useSavingsPlan, useUserProfile } from "@/api/hooks";
import type { PermittedProfile } from "@/contracts/outputs/permitted_profile";
import { Button, ErrorState, Loading, Notice, PageHeader, Section, StatusBadge, Surface, cn } from "@/components/ui";
import { formatAmount, formatMoney, formatMonth, formatNumber, formatPercent } from "@/lib/format";
import { t, tDynamic } from "@/i18n";

function factorValue(name: string, value: number): string {
  if (name === "reserve_coverage" || name === "stress_coverage") return t("plan.factors.units.months", { value: formatNumber(value, 2) });
  if (name === "debt_service" || name === "conservative_headroom") return formatPercent(value);
  return formatNumber(value, 2);
}

export function PlanPage() {
  const { identity } = usePersona();
  const profile = useUserProfile();
  if (profile.isPending) return <Loading className="max-w-5xl" />;

  const tolerance = profile.isError ? "conservative" : profile.data?.data?.declared_tolerance ?? "conservative";
  return <PlanForProfile key={identity.user_id} tolerance={tolerance} />;
}

function PlanForProfile({ tolerance }: { tolerance: PermittedProfile["tolerance"] }) {
  const state = useFinancialState();
  const capacity = useCapacity();
  const permitted = usePermittedProfile(tolerance);
  const plan = useSavingsPlan(permitted.data?.data?.permitted);

  const queries = [state, capacity, permitted, plan];
  const failed = queries.find((q) => q.isError);
  if (failed) return <ErrorState error={failed.error} onRetry={() => queries.forEach((q) => void q.refetch())} />;
  if (queries.some((q) => q.isPending)) return <Loading className="max-w-5xl" />;

  const currency = state.data!.data!.currency;
  const cap = capacity.data!.data!;
  const prof = permitted.data!.data!;
  const p = plan.data!.data!;
  const noRule = p.amount <= 0 || !p.start_month;
  const capped = prof.permitted !== prof.tolerance;

  return (
    <>
      <PageHeader
        title={noRule ? t("plan.titleNone") : t("plan.titleRule", { amount: formatMoney(p.amount, currency), month: formatMonth(p.start_month!, "long") })}
        subtitle={t("plan.subtitle")}
        actions={
          !noRule && (
            <Button asChild variant="primary">
              <Link to="/copilot" state={{ prompt: "Help me save for my trip." }}>
                {t("plan.propose")}
                <ArrowRight aria-hidden className="size-4" />
              </Link>
            </Button>
          )
        }
      />

      {p.hard_rules_triggered.length > 0 && (
        <div className="mb-10 space-y-3">
          {p.hard_rules_triggered.map((rule) => (
            <Notice key={rule} tone="danger" icon={Prohibit} title={tDynamic("plan.hardRules", rule)}>
              <span className="font-mono text-xs">{rule}</span>
            </Notice>
          ))}
        </div>
      )}

      <Section id="profile" title={t("plan.profile.title")} subtitle={t("plan.profile.explain")}>
        <Surface className="grid gap-8 p-6 md:grid-cols-[1.2fr_auto_1fr_auto_1fr] md:items-center">
          <div>
            <p className="text-sm text-ink-2">{t("plan.profile.tolerance")}</p>
            <p className="mt-1 text-lg font-semibold text-ink">{t(`plan.profile.levels.${tolerance}`)}</p>
          </div>
          <span aria-hidden className="hidden text-ink-3 md:block">
            min
          </span>
          <div>
            <p className="text-sm text-ink-2">{t("plan.profile.capacity")}</p>
            <p className="mt-1 text-lg font-semibold text-ink">{tDynamic("plan.profile.levels", cap.level)}</p>
          </div>
          <span aria-hidden className="hidden text-ink-3 md:block">
            =
          </span>
          <div>
            <p className="text-sm text-ink-2">{t("plan.profile.permitted")}</p>
            <p className="mt-1 flex items-center gap-2 text-lg font-semibold text-ink">
              {tDynamic("plan.profile.levels", prof.permitted)}
              {capped && <StatusBadge tone="warning">{t("plan.profile.capped")}</StatusBadge>}
            </p>
          </div>
        </Surface>
      </Section>

      <div className="mt-12 grid gap-12 xl:grid-cols-[1fr_1fr]">
        <Section id="factors" title={t("plan.factors.title")}>
          <table className="w-full text-sm">
            <caption className="sr-only">{t("plan.factors.title")}</caption>
            <tbody>
              {cap.factors.map((f) => {
                const binding = cap.binding_factors.includes(f.name);
                return (
                  <tr key={f.name} className="border-b border-line last:border-0">
                    <th scope="row" className="py-3 pr-4 text-left font-normal">
                      <span className="text-ink">{tDynamic("plan.factors.names", f.name)}</span>
                      <span className="mt-0.5 block text-xs text-ink-3">{f.measure}</span>
                    </th>
                    <td className="num py-3 pr-4 text-right whitespace-nowrap text-ink">{factorValue(f.name, f.value)}</td>
                    <td className="py-3 text-right">
                      <span className="inline-flex items-center gap-2">
                        {binding && (
                          <StatusBadge tone="danger" icon={Warning}>
                            {t("plan.factors.binding")}
                          </StatusBadge>
                        )}
                        <span className="text-xs text-ink-2">{tDynamic("plan.factors.bands", f.band)}</span>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Section>

        <Section id="allocation" title={t("plan.allocation.title")}>
          {p.requirements.length === 0 ? (
            <p className="text-sm text-ink-2">{t("common.none")}</p>
          ) : (
            <table className="w-full text-sm">
              <caption className="sr-only">{t("plan.allocation.title")}</caption>
              <thead>
                <tr className="border-b border-line text-left text-xs text-ink-3">
                  <th scope="col" className="py-2 pr-4 font-medium">
                    {t("plan.allocation.bucket")}
                  </th>
                  <th scope="col" className="py-2 pr-4 text-right font-medium">
                    {t("plan.allocation.required")} ({currency})
                  </th>
                  <th scope="col" className="py-2 pr-4 text-right font-medium">
                    {t("plan.allocation.funded")} ({currency})
                  </th>
                  <th scope="col" className="py-2 text-right font-medium">
                    {t("plan.allocation.from")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {p.requirements.map((r) => {
                  const goalId = r.bucket.startsWith("goal:") ? r.bucket.slice(5) : null;
                  const goal = goalId ? p.goal_status.find((g) => g.goal_id === goalId) : undefined;
                  return (
                    <tr key={r.bucket} className="border-b border-line last:border-0">
                      <th scope="row" className="py-3 pr-4 text-left font-normal text-ink">
                        {goalId ? t("plan.allocation.goal", { name: goal?.name ?? goalId }) : t("plan.allocation.reserve")}
                      </th>
                      <td className="num py-3 pr-4 text-right text-ink-2">{formatAmount(r.required_monthly, currency)}</td>
                      <td className={cn("num py-3 pr-4 text-right", r.funded_monthly > 0 ? "font-medium text-ink" : "text-ink-3")}>
                        {formatAmount(r.funded_monthly, currency)}
                      </td>
                      <td className="py-3 text-right text-ink-2">{r.funded_from ? formatMonth(r.funded_from) : t("plan.allocation.notFunded")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          {plan.data!.warnings.map((w) => (
            <p key={w.code} className="mt-4 flex gap-2 text-sm text-ink-2">
              <Warning aria-hidden weight="bold" className="mt-0.5 size-4 shrink-0 text-warning" />
              {w.message}
            </p>
          ))}
        </Section>
      </div>
    </>
  );
}
