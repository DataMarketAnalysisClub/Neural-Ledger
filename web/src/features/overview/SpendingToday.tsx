import { Link } from "react-router-dom";
import { Receipt } from "@phosphor-icons/react";
import { useSpending } from "@/api/hooks";
import { fact } from "@/api/client";
import { Button, Money, Surface, cn } from "@/components/ui";
import { formatDate, formatMoney } from "@/lib/format";
import { t, tDynamic } from "@/i18n";

/**
 * The daily figure (ADR-039): what the conservative forecast counts on for the pay cycle of today, less the receipts
 * and statement charges logged in it, per day until payday. Every number is the API's; nothing is computed here but
 * the width of the bars. Without a financial model the API answers INSUFFICIENT_DATA and the card stays out of the way.
 */
export function SpendingToday({ currency }: { currency: string }) {
  const spending = useSpending();
  const envelope = spending.data;
  const status = envelope?.data;
  if (!status) return null;
  const c = status.check;
  const share = c.assumed > 0 ? Math.min(100, (c.logged / c.assumed) * 100) : 0;
  const over = c.overspend > 0;
  return (
    <Surface className="p-6 sm:p-8">
      <section id="spending-today" aria-labelledby="spending-today-title" className="grid gap-8 lg:grid-cols-[1fr_minmax(0,320px)]">
        <div className="min-w-0">
          <h2 id="spending-today-title" className="text-sm font-medium text-ink-2">
            {t("overview.spending.title")}
          </h2>
          <p className="mt-2 text-3xl font-semibold tracking-tight text-ink">
            <Money
              amount={c.per_day}
              currency={currency}
              provenance={{ fact: fact(envelope, "spending.per_day"), snapshotId: envelope.snapshot_id, paramsVersion: envelope.params_version }}
            />
            <span className="ml-1.5 text-base font-normal text-ink-2">{t("overview.spending.daySuffix")}</span>
          </p>
          <p className="mt-1 text-sm text-ink-2">{t("overview.spending.until", { days: c.days_left, date: formatDate(c.window_end) })}</p>

          <div
            className="mt-5 h-2.5 overflow-hidden rounded-full bg-rail"
            role="img"
            aria-label={t("overview.spending.bar", { logged: formatMoney(c.logged, currency), assumed: formatMoney(c.assumed, currency) })}
          >
            <div className={cn("h-full rounded-full", over ? "bg-danger" : "bg-accent")} style={{ width: `${share}%` }} />
          </div>
          <p className="mt-2 flex flex-wrap justify-between gap-x-4 gap-y-1 text-xs text-ink-2">
            <span>{t("overview.spending.bar", { logged: formatMoney(c.logged, currency), assumed: formatMoney(c.assumed, currency) })}</span>
            <span className={cn("font-medium", over ? "text-danger" : "text-ink")}>
              {over ? t("overview.spending.over", { amount: formatMoney(c.overspend, currency) }) : t("overview.spending.left", { amount: formatMoney(c.left, currency) })}
            </span>
          </p>
          <p className="mt-4 text-xs text-ink-3">{t("overview.spending.note")}</p>
          <Button asChild variant="secondary" size="sm" className="mt-4">
            <Link to="/copilot">
              <Receipt aria-hidden className="size-4" />
              {t("overview.spending.add")}
            </Link>
          </Button>
        </div>

        {c.categories.length > 0 && (
          <div className="min-w-0 lg:border-l lg:border-line lg:pl-8">
            <h3 className="text-xs font-medium text-ink-3">{t("overview.spending.categories")}</h3>
            <ul className="mt-3 space-y-3">
              {c.categories.map((cat) => {
                // A label the forecast has no budget for (uncategorized, other): the amount alone, no bar to fill.
                const budgeted = cat.assumed > 0;
                const part = budgeted ? Math.min(100, (cat.logged / cat.assumed) * 100) : 0;
                const label = budgeted
                  ? t("overview.spending.category", { logged: formatMoney(cat.logged, currency), assumed: formatMoney(cat.assumed, currency) })
                  : formatMoney(cat.logged, currency);
                return (
                  <li key={cat.category} className="text-sm">
                    <div className="flex justify-between gap-3">
                      <span className="text-ink">{tDynamic("statements.categories", cat.category)}</span>
                      <span className="num text-xs text-ink-2">{label}</span>
                    </div>
                    {budgeted && (
                      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-rail" role="img" aria-label={`${tDynamic("statements.categories", cat.category)}: ${label}`}>
                        <div className={cn("h-full rounded-full", cat.logged > cat.assumed ? "bg-danger" : "bg-ink")} style={{ width: `${part}%` }} />
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </section>
    </Surface>
  );
}
