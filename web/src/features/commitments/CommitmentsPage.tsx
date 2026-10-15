import { ShieldWarning } from "@phosphor-icons/react";
import { useCapacity, useCommitments, useFinancialState } from "@/api/hooks";
import { fact } from "@/api/client";
import { CommitmentBars } from "@/components/charts";
import { RedactedText, redactedPlainText } from "@/components/redaction";
import { ErrorState, Loading, PageHeader, Section, StatusBadge, Surface } from "@/components/ui";
import { formatAmount, formatMoney, formatMonth, formatPercent } from "@/lib/format";
import { t, tDynamic } from "@/i18n";

export function CommitmentsPage() {
  const commitments = useCommitments();
  const capacity = useCapacity();
  const state = useFinancialState();

  const queries = [commitments, capacity, state];
  const failed = queries.find((q) => q.isError);
  if (failed) return <ErrorState error={failed.error} onRetry={() => queries.forEach((q) => void q.refetch())} />;
  if (queries.some((q) => q.isPending)) return <Loading className="max-w-5xl" />;

  const c = commitments.data!.data!;
  const currency = state.data!.data!.currency;
  const first = c.schedule[0];
  const debtService = capacity.data!.data!.factors.find((f) => f.name === "debt_service");

  return (
    <>
      <PageHeader
        title={first ? t("commitments.title", { amount: formatMoney(first.total, currency), month: formatMonth(first.month, "long") }) : t("nav.commitments")}
        subtitle={t("commitments.subtitle")}
      />

      <div className="grid gap-12 xl:grid-cols-[1fr_300px]">
        <Section id="commitments-table">
          <Surface className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <caption className="sr-only">{t("commitments.table.caption")}</caption>
              <thead>
                <tr className="border-b border-line text-left text-xs text-ink-3">
                  <th scope="col" className="px-5 py-3 font-medium">
                    {t("commitments.table.name")}
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium">
                    {t("commitments.table.type")}
                  </th>
                  <th scope="col" className="px-5 py-3 text-right font-medium">
                    {t("commitments.table.amount")} ({currency})
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium">
                    {t("commitments.table.from")}
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium">
                    {t("commitments.table.to")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {c.commitments.map((item) => (
                  <tr key={item.commitment_id} className="border-b border-line last:border-0">
                    <th scope="row" className="max-w-[280px] px-5 py-3 text-left font-normal text-ink">
                      {/* Untrusted merchant text: plain text, never markup or instructions. Placeholders for personal data
                          removed at import become translated chips. */}
                      <span className="line-clamp-2 break-words" title={redactedPlainText(item.label.untrusted_text)}>
                        <RedactedText text={item.label.untrusted_text} />
                      </span>
                    </th>
                    <td className="px-5 py-3 text-ink-2">
                      <span className="inline-flex items-center gap-2 whitespace-nowrap">
                        {tDynamic("commitments.types", item.type)}
                        {item.is_debt && <StatusBadge tone="neutral">{t("commitments.table.debt")}</StatusBadge>}
                      </span>
                    </td>
                    <td className="num px-5 py-3 text-right text-ink">{formatAmount(item.amount, currency)}</td>
                    <td className="px-5 py-3 whitespace-nowrap text-ink-2">{formatMonth(item.first_due)}</td>
                    <td className="px-5 py-3 whitespace-nowrap text-ink-2">{item.last_due ? formatMonth(item.last_due) : t("common.ongoing")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Surface>
          <p className="mt-3 flex items-center gap-1.5 text-xs text-ink-3">
            <ShieldWarning aria-hidden className="size-4" />
            {t("commitments.untrusted")}
          </p>

          <div className="mt-12">
            <CommitmentBars months={c.schedule} currency={currency} />
          </div>
        </Section>

        {debtService && (
          <Section id="debt" title={t("commitments.debtService.title")} className="xl:border-l xl:border-line xl:pl-10">
            <p className="num text-2xl font-semibold text-ink">{formatPercent(debtService.value)}</p>
            <p className="mt-2 text-sm text-ink-2">{t("commitments.debtService.body")}</p>
            <p className="mt-4">
              <StatusBadge tone={debtService.band === "low" ? "danger" : debtService.band === "medium" ? "warning" : "positive"}>
                {tDynamic("plan.factors.bands", debtService.band)}
              </StatusBadge>
            </p>
            <p className="mt-4 text-xs text-ink-3">{fact(capacity.data, "capacity.debt_service.value")?.derivation ?? debtService.measure}</p>
          </Section>
        )}
      </div>
    </>
  );
}
