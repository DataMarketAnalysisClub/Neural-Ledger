import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ChatText, CheckCircle, Question, WarningOctagon } from "@phosphor-icons/react";
import { useFinancialState, useForecast, useProtectedSurplus, useSavingsPlan } from "@/api/hooks";
import { fact } from "@/api/client";
import { LiquidityBridge } from "@/components/LiquidityBridge";
import { ForecastChart, type ForecastPoint } from "@/components/charts";
import { Button, ErrorState, Loading, Money, PageHeader, Section, Surface, cn } from "@/components/ui";
import { formatMoney, formatMonth } from "@/lib/format";
import { t } from "@/i18n";
import { GuidePanel, type GuideStep } from "./OverviewGuide";

export function OverviewPage() {
  const [guideStep, setGuideStep] = useState<number | null>(null);
  const guideButton = useRef<HTMLButtonElement>(null);
  const state = useFinancialState();
  const conservative = useForecast("conservative");
  const typical = useForecast("typical");
  const surplus = useProtectedSurplus();
  const plan = useSavingsPlan();

  const queries = [state, conservative, typical, surplus];
  const failed = queries.find((q) => q.isError);
  if (failed) return <ErrorState error={failed.error} onRetry={() => queries.forEach((q) => void q.refetch())} />;
  if (queries.some((q) => q.isPending)) return <Loading className="max-w-5xl" />;

  const s = state.data!.data!;
  const fc = conservative.data!.data!;
  const ft = typical.data!.data!;
  const sp = surplus.data!.data!;
  const currency = s.currency;
  const binding = sp.binding_month ?? fc.cycles.at(-1)!.month;
  const bindingIndex = fc.cycles.findIndex((c) => c.month === binding);
  const bridgeCycles = fc.cycles.slice(0, bindingIndex + 1);
  const short = sp.protected_surplus < 0;

  const points: ForecastPoint[] = fc.cycles.map((c, i) => ({
    month: c.month,
    conservative: c.trough,
    conservativeHeadroom: c.headroom,
    typical: ft.cycles[i]?.trough ?? c.trough,
  }));

  const title = short
    ? t("overview.titleShort", { month: formatMonth(binding, "long"), amount: formatMoney(-sp.protected_surplus, currency) })
    : t("overview.titleProtected", {
        month: formatMonth(binding, "long"),
        protected: formatMoney(sp.protected_surplus, currency),
        balance: formatMoney(s.checking, currency),
      });

  const goal = plan.data?.data?.goal_status[0];

  // One step per region, in reading order; the goal step only when there is a goal.
  const guide: GuideStep[] = [
    { target: "page-title", title: t("overview.guide.headline.title"), body: short ? t("overview.guide.headline.bodyShort") : t("overview.guide.headline.body") },
    { target: "guide-bridge", title: t("overview.guide.bridge.title"), body: t("overview.guide.bridge.body") },
    { target: "guide-chart", title: t("overview.guide.chart.title"), body: t("overview.guide.chart.body") },
    { target: "flow", title: t("overview.guide.flow.title"), body: t("overview.guide.flow.body") },
    { target: "reserve", title: t("overview.guide.reserve.title"), body: t("overview.guide.reserve.body") },
    ...(goal ? [{ target: "goal", title: t("overview.guide.goal.title"), body: t("overview.guide.goal.body") }] : []),
    { target: "guide-copilot", title: t("overview.guide.copilot.title"), body: t("overview.guide.copilot.body") },
  ];

  return (
    <>
      <PageHeader
        title={title}
        subtitle={short ? t("overview.subtitleShort") : t("overview.subtitle")}
        actions={
          <>
            <Button
              ref={guideButton}
              onClick={() => setGuideStep(0)}
              aria-label={t("overview.guide.open")}
              title={t("overview.guide.open")}
              aria-expanded={guideStep !== null}
              className="w-10 px-0"
            >
              <Question aria-hidden className="size-5" />
            </Button>
            <Button asChild variant="primary">
              <Link to="/copilot" id="guide-copilot">
                <ChatText aria-hidden className="size-4" />
                {t("common.askCopilot")}
              </Link>
            </Button>
          </>
        }
      />

      <div id="guide-bridge">
        <Surface className={cn("p-6 sm:p-8", short ? "border-danger/25 bg-danger-bg" : "border-positive/25 bg-positive-bg")}>
          <LiquidityBridge
            currency={currency}
            balance={fc.opening_trough}
            cycles={bridgeCycles}
            floor={fc.floor}
            protectedSurplus={sp.protected_surplus}
            bindingMonth={binding}
            snapshotId={surplus.data!.snapshot_id}
            paramsVersion={surplus.data!.params_version}
            facts={surplus.data!.facts}
          />
        </Surface>
      </div>

      <div className="mt-12 grid gap-12 xl:grid-cols-[1fr_300px]">
        <div id="guide-chart" className="min-w-0">
          <ForecastChart points={points} floor={fc.floor} currency={currency} bindingMonth={binding} />
        </div>

        <div className="space-y-10 xl:border-l xl:border-line xl:pl-10">
          <Section id="flow" title={t("overview.flow.title")} subtitle={t("overview.flow.subtitle")}>
            <table className="w-full text-sm">
              <caption className="sr-only">{t("overview.flow.title")}</caption>
              <thead className="sr-only">
                <tr>
                  <th scope="col">{t("common.month")}</th>
                  <th scope="col">{currency}</th>
                </tr>
              </thead>
              <tbody>
                {sp.monthly_free_flow.map((m) => (
                  <tr key={m.month} className="border-b border-line last:border-0">
                    <th scope="row" className="py-2 text-left font-normal text-ink-2">
                      {formatMonth(m.month)}
                    </th>
                    <td className={cn("num py-2 text-right", m.amount < 0 ? "font-medium text-ink" : "text-ink")}>
                      {formatMoney(m.amount, currency, { signed: true })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-3 text-xs text-ink-3">{t("overview.flow.note")}</p>
          </Section>

          <Section id="reserve" title={t("overview.reserve.title")}>
            <p className="text-xl font-semibold text-ink">
              <Money
                amount={s.reserve}
                currency={currency}
                provenance={{ fact: fact(state.data, "balance.reserve"), snapshotId: state.data!.snapshot_id, paramsVersion: state.data!.params_version }}
              />
            </p>
            <p className="mt-1 text-xs text-ink-3">{t("overview.reserve.note")}</p>
          </Section>

          {goal && (
            <Section id="goal" title={t("overview.goal.title", { name: goal.name ?? goal.goal_id })}>
              <p className="text-sm text-ink-2">
                {t("overview.goal.progress", { saved: formatMoney(goal.saved, currency), target: formatMoney(goal.target, currency) })}
              </p>
              <div
                className="mt-3 h-2 overflow-hidden rounded-full bg-rail"
                role="img"
                aria-label={t("overview.goal.progress", { saved: formatMoney(goal.saved, currency), target: formatMoney(goal.target, currency) })}
              >
                <div className="h-full rounded-full bg-ink" style={{ width: `${Math.min(100, (goal.saved / goal.target) * 100)}%` }} />
              </div>
              <p className="mt-3 flex items-center gap-1.5 text-xs text-ink-2">
                {goal.on_track ? (
                  <CheckCircle aria-hidden weight="bold" className="size-3.5 text-positive" />
                ) : (
                  <WarningOctagon aria-hidden weight="bold" className="size-3.5 text-danger" />
                )}
                {goal.on_track ? t("overview.goal.onTrack") : t("overview.goal.offTrack")}
                <span className="text-ink-3">{t("overview.goal.deadline", { month: formatMonth(goal.deadline) })}</span>
              </p>
            </Section>
          )}
        </div>
      </div>

      {guideStep !== null && (
        <GuidePanel
          steps={guide}
          step={guideStep}
          onStep={setGuideStep}
          onClose={() => {
            setGuideStep(null);
            guideButton.current?.focus();
          }}
        />
      )}
    </>
  );
}
