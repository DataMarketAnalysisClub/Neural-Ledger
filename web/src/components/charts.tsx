/**
 * Charts, built to the dataviz method: emphasis form (the series that matters in ink,
 * context in gray), a named threshold for the safety floor, direct labels, a legend with line
 * samples, a crosshair tooltip, keyboard access, and a table view. Text never wears a series color.
 */
import { useState, type ReactNode } from "react";
import * as Collapsible from "@radix-ui/react-collapsible";
import { CaretDown, WarningOctagon } from "@phosphor-icons/react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import { formatAmount, formatMoney, formatMonth, moneyForSpeech } from "@/lib/format";
import { t } from "@/i18n";
import { cn } from "./ui";

const COLORS = {
  focus: "var(--series-focus)",
  context: "var(--series-context)",
  floor: "var(--floor)",
  grid: "var(--grid)",
  axis: "var(--text-3)",
};

/** Round axis steps (1, 2, 2.5 or 5 times a power of ten) covering [min, max], with one unit for all ticks. */
export function niceAxis(min: number, max: number, target = 5): { domain: [number, number]; ticks: number[]; unit: "M" | "k" | "" } {
  const raw = (max - min || 1) / (target - 1);
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = ([1, 2, 2.5, 5, 10].find((m) => m * magnitude >= raw) ?? 10) * magnitude;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v));
  const peak = Math.max(Math.abs(lo), Math.abs(hi));
  return { domain: [lo, hi], ticks, unit: peak >= 1_000_000 ? "M" : peak >= 1_000 ? "k" : "" };
}

function axisLabel(value: number, unit: "M" | "k" | ""): string {
  const sign = value < 0 ? "−" : "";
  const abs = Math.abs(value);
  if (abs === 0) return "0";
  if (unit === "M") return `${sign}${(abs / 1_000_000).toLocaleString("en-US", { maximumFractionDigits: 2 })}M`;
  if (unit === "k") return `${sign}${(abs / 1_000).toLocaleString("en-US", { maximumFractionDigits: 1 })}k`;
  return `${sign}${abs}`;
}

/** A legend entry whose sample matches the mark: solid or dashed line, or a swatch. */
function LegendItem({ label, sample }: { label: string; sample: "solid" | "dashed" | "floor" | "swatch-focus" | "swatch-context" }) {
  return (
    <li className="inline-flex items-center gap-2 text-xs text-ink-2">
      <svg aria-hidden width="22" height="10" className="shrink-0">
        {sample === "solid" && <line x1="1" y1="5" x2="21" y2="5" stroke={COLORS.focus} strokeWidth="2.5" strokeLinecap="round" />}
        {sample === "dashed" && <line x1="1" y1="5" x2="21" y2="5" stroke={COLORS.context} strokeWidth="2" strokeDasharray="4 3" strokeLinecap="round" />}
        {sample === "floor" && <line x1="1" y1="5" x2="21" y2="5" stroke={COLORS.floor} strokeWidth="1.5" strokeDasharray="8 3" />}
        {sample === "swatch-focus" && <rect x="5" y="0" width="12" height="10" rx="2" fill={COLORS.focus} />}
        {sample === "swatch-context" && <rect x="5" y="0" width="12" height="10" rx="2" fill={COLORS.context} fillOpacity={0.45} />}
      </svg>
      {label}
    </li>
  );
}

/** "Show the numbers": every chart has a table view. */
export function DataTable({ caption, children }: { caption: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <Collapsible.Root open={open} onOpenChange={setOpen} className="mt-4">
      <Collapsible.Trigger className="inline-flex h-8 items-center gap-1.5 rounded-control px-2 text-sm text-ink-2 hover:bg-rail hover:text-ink">
        <CaretDown aria-hidden className={cn("size-4 transition-transform duration-150", open && "rotate-180")} />
        {open ? t("common.hideNumbers") : t("common.showNumbers")}
      </Collapsible.Trigger>
      <Collapsible.Content className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[480px] text-sm">
          <caption className="sr-only">{caption}</caption>
          {children}
        </table>
      </Collapsible.Content>
    </Collapsible.Root>
  );
}

// ---- Forecast ----------------------------------------------------------------------------------------

export interface ForecastPoint {
  month: string;
  typical: number;
  conservative: number;
  conservativeHeadroom: number;
}

export function ForecastChart({
  points,
  floor,
  currency,
  bindingMonth,
}: {
  points: ForecastPoint[];
  floor: number;
  currency: string;
  bindingMonth: string;
}) {
  const binding = points.find((p) => p.month === bindingMonth);
  const values = points.flatMap((p) => [p.typical, p.conservative]).concat(floor, 0);
  const min = Math.min(...values);
  const max = Math.max(...values);
  // Axis geometry only: round steps and one unit for every tick (never mixing k and M).
  const { domain, ticks, unit } = niceAxis(min, max);
  const breach = (binding?.conservativeHeadroom ?? 0) < 0;
  // Direct labels need room on the right; on narrow screens the legend carries series identity instead.
  const [width, setWidth] = useState(0);
  const narrow = width > 0 && width < 560;
  const note = binding
    ? breach
      ? t("overview.chart.below", { amount: formatMoney(binding.conservativeHeadroom, currency) })
      : t("overview.chart.above", { amount: formatMoney(binding.conservativeHeadroom, currency) })
    : "";
  const summary = binding
    ? t("overview.chart.summary", { amount: formatMoney(binding.conservative, currency), month: formatMonth(bindingMonth, "long"), floor: formatMoney(floor, currency) })
    : "";

  return (
    <figure aria-labelledby="forecast-title" aria-describedby="forecast-summary" className="min-w-0">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h2 id="forecast-title" className="text-lg font-semibold text-ink">
            {t("overview.chart.title")}
          </h2>
          <p className="mt-0.5 text-sm text-ink-3">{t("overview.chart.subtitle", { currency })}</p>
        </div>
        <ul className="flex flex-wrap gap-x-5 gap-y-1" aria-label="Legend">
          <LegendItem label={t("overview.chart.conservative")} sample="solid" />
          <LegendItem label={t("overview.chart.typical")} sample="dashed" />
          <LegendItem label={t("overview.chart.floor")} sample="floor" />
        </ul>
      </div>
      <p id="forecast-summary" className="sr-only">
        {summary}
      </p>
      <div className="mt-4 h-72" role="img" aria-label={summary}>
        <ResponsiveContainer width="100%" height="100%" onResize={(w) => setWidth(w)}>
          <LineChart data={points} margin={{ top: 36, right: narrow ? 12 : 156, bottom: 4, left: 4 }} accessibilityLayer>
            <CartesianGrid stroke={COLORS.grid} vertical={false} />
            <XAxis
              dataKey="month"
              tickFormatter={(m: string) => formatMonth(m)}
              tick={{ fill: COLORS.axis, fontSize: 12 }}
              axisLine={{ stroke: COLORS.grid }}
              tickLine={false}
              tickMargin={8}
            />
            <YAxis
              domain={domain}
              ticks={ticks}
              tickFormatter={(v: number) => axisLabel(v, unit)}
              tick={{ fill: COLORS.axis, fontSize: 12 }}
              axisLine={false}
              tickLine={false}
              width={48}
            />
            <ReferenceArea y1={domain[0]} y2={floor} fill="var(--danger)" fillOpacity={0.05} ifOverflow="hidden" />
            {domain[0] < 0 && <ReferenceLine y={0} stroke="var(--border-control)" strokeWidth={1} />}
            <ReferenceLine
              y={floor}
              stroke={COLORS.floor}
              strokeWidth={1.5}
              strokeDasharray="8 3"
              label={(props: { viewBox?: { x: number; y: number; width: number } }) => {
                // Inside the plot, right-aligned just above the floor line: never shares the tick row.
                const vb = props.viewBox;
                if (!vb) return <g />;
                return (
                  <text x={vb.x + vb.width - 4} y={vb.y - 6} textAnchor="end" fontSize={12} fontWeight={500} fill="var(--danger)">
                    {t("overview.chart.floor")} {formatMoney(floor, currency)}
                  </text>
                );
              }}
            />
            <Tooltip content={<ForecastTooltip currency={currency} floor={floor} />} cursor={{ stroke: "var(--border-control)", strokeWidth: 1 }} />
            <Line
              type="linear"
              dataKey="typical"
              name={t("overview.chart.typical")}
              stroke={COLORS.context}
              strokeWidth={2}
              strokeDasharray="5 4"
              dot={false}
              activeDot={{ r: 4, fill: COLORS.context, stroke: "var(--bg-surface)", strokeWidth: 2 }}
              isAnimationActive={false}
              label={narrow ? undefined : <EndLabel last={points.length - 1} text={t("overview.chart.typical")} color="var(--text-2)" />}
            />
            <Line
              type="linear"
              dataKey="conservative"
              name={t("overview.chart.conservative")}
              stroke={COLORS.focus}
              strokeWidth={2.5}
              dot={{ r: 4, fill: COLORS.focus, stroke: "var(--bg-surface)", strokeWidth: 2 }}
              activeDot={{ r: 5, fill: COLORS.focus, stroke: "var(--bg-surface)", strokeWidth: 2 }}
              isAnimationActive={false}
              label={narrow ? undefined : <EndLabel last={points.length - 1} text={t("overview.chart.conservative")} color="var(--text)" />}
            />
            {binding && (
              <ReferenceDot
                x={binding.month}
                y={binding.conservative}
                r={6}
                fill={breach ? "var(--danger)" : COLORS.focus}
                stroke="var(--bg-surface)"
                strokeWidth={2}
                label={(props: { viewBox?: { x: number; y: number; width: number; height: number } }) => {
                  // The note sits in the top margin with a leader line down to the point, so it never
                  // collides with the axes, the floor or either series, whatever the data looks like.
                  const vb = props.viewBox;
                  if (!vb) return <g />;
                  const cx = vb.x + vb.width / 2;
                  const cy = vb.y + vb.height / 2;
                  const anchor = width && cx > width * 0.65 ? "end" : width && cx < width * 0.3 ? "start" : "middle";
                  return (
                    <g>
                      <line x1={cx} y1={18} x2={cx} y2={cy - 9} stroke="var(--text-3)" strokeWidth={1} strokeDasharray="2 2" />
                      <text x={cx} y={12} textAnchor={anchor} fontSize={12} fontWeight={600} fill={breach ? "var(--danger)" : "var(--text)"}>
                        {note}
                      </text>
                    </g>
                  );
                }}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <DataTable caption={t("overview.chart.title")}>
        <thead>
          <tr className="border-b border-line text-left text-xs text-ink-3">
            <th scope="col" className="py-2 pr-4 font-medium">
              {t("common.month")}
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">
              {t("overview.chart.typical")} ({currency})
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">
              {t("overview.chart.conservative")} ({currency})
            </th>
            <th scope="col" className="py-2 text-right font-medium">
              {t("overview.chart.floor")} ({currency})
            </th>
          </tr>
        </thead>
        <tbody>
          {points.map((p) => (
            <tr key={p.month} className="border-b border-line last:border-0">
              <th scope="row" className="py-2 pr-4 text-left font-normal text-ink-2">
                {formatMonth(p.month)}
              </th>
              <td className="num py-2 pr-4 text-right">{formatAmount(p.typical, currency)}</td>
              <td className={cn("num py-2 pr-4 text-right", p.conservativeHeadroom < 0 && "font-semibold text-danger")}>
                {formatAmount(p.conservative, currency)}
                {p.conservativeHeadroom < 0 && <WarningOctagon aria-label="below the floor" weight="bold" className="ml-1 inline size-3.5 align-[-2px]" />}
              </td>
              <td className="num py-2 text-right text-ink-2">{formatAmount(floor, currency)}</td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </figure>
  );
}

function EndLabel(props: { x?: number; y?: number; index?: number; last: number; text: string; color: string }) {
  if (props.index !== props.last || props.x === undefined || props.y === undefined) return null;
  return (
    <text x={props.x + 10} y={props.y} dy={4} fontSize={12} fontWeight={500} fill={props.color}>
      {props.text}
    </text>
  );
}

function ForecastTooltip({ active, payload, label, currency, floor }: TooltipProps<number, string> & { currency: string; floor: number }) {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload as ForecastPoint | undefined;
  if (!point) return null;
  return (
    <div className="rounded-object border border-line bg-surface px-3 py-2 text-xs shadow-object">
      <p className="mb-1.5 font-medium text-ink">{formatMonth(String(label), "long")}</p>
      <dl className="grid grid-cols-[auto_auto] gap-x-4 gap-y-1">
        <dt className="text-ink-2">{t("overview.chart.conservative")}</dt>
        <dd className="num text-right font-medium text-ink">{formatMoney(point.conservative, currency)}</dd>
        <dt className="text-ink-2">{t("overview.chart.typical")}</dt>
        <dd className="num text-right text-ink">{formatMoney(point.typical, currency)}</dd>
        <dt className="text-ink-2">{t("overview.chart.floor")}</dt>
        <dd className="num text-right text-ink">{formatMoney(floor, currency)}</dd>
      </dl>
    </div>
  );
}

// ---- Headroom dumbbell (simulator) -----------------------------------------------------------------

export interface HeadroomRow {
  scenario: "typical" | "conservative" | "stress";
  before: number;
  after: number;
  month: string;
}

/** Margin above the floor before and after a purchase. Zero is the safety floor. */
export function HeadroomDumbbell({ rows, currency }: { rows: HeadroomRow[]; currency: string }) {
  const values = rows.flatMap((r) => [r.before, r.after]).concat(0);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (v: number) => ((v - min) / span) * 100;
  const zero = x(0);
  return (
    <figure aria-labelledby="impact-title" className="min-w-0">
      <h3 id="impact-title" className="text-base font-semibold text-ink">
        {t("simulator.impact.title")}
      </h3>
      <p className="mt-0.5 text-sm text-ink-3">{t("simulator.impact.subtitle")}</p>
      <ul className="mt-2 flex gap-5" aria-hidden>
        <li className="inline-flex items-center gap-2 text-xs text-ink-2">
          <span className="size-3 rounded-full border-2 border-[var(--series-context)] bg-surface" />
          {t("simulator.impact.before")}
        </li>
        <li className="inline-flex items-center gap-2 text-xs text-ink-2">
          <span className="size-3 rounded-full bg-[var(--series-focus)]" />
          {t("simulator.impact.after")}
        </li>
      </ul>
      <ol className="mt-5 space-y-6">
        {rows.map((r) => {
          const breach = r.after < 0;
          const name = t(`simulator.impact.scenario.${r.scenario}`);
          const left = Math.min(x(r.before), x(r.after));
          const width = Math.abs(x(r.before) - x(r.after));
          return (
            <li key={r.scenario}>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm font-medium text-ink">{name}</p>
                <p className="num text-sm text-ink-2">
                  <span className="sr-only">
                    {t("simulator.impact.summary", {
                      scenario: name,
                      before: moneyForSpeech(r.before, currency),
                      after: moneyForSpeech(r.after, currency),
                      month: formatMonth(r.month, "long"),
                    })}
                  </span>
                  <span aria-hidden>
                    {formatMoney(r.before, currency)} <span className="text-ink-3">to</span>{" "}
                    <span className={cn("font-semibold", breach ? "text-danger" : "text-ink")}>{formatMoney(r.after, currency)}</span>
                  </span>
                </p>
              </div>
              <div className="relative mt-3 h-6" aria-hidden>
                <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-line" />
                <div className="absolute inset-y-0 bg-danger/[0.06]" style={{ left: 0, width: `${zero}%` }} />
                <div className="absolute inset-y-[-6px] w-px bg-danger" style={{ left: `${zero}%` }} />
                <div className="absolute top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-[var(--series-context)]/50" style={{ left: `${left}%`, width: `${width}%` }} />
                <div
                  className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--series-context)] bg-surface"
                  style={{ left: `${x(r.before)}%` }}
                />
                <div
                  className={cn("absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface", breach ? "bg-danger" : "bg-[var(--series-focus)]")}
                  style={{ left: `${x(r.after)}%` }}
                />
              </div>
              {breach && (
                <p className="mt-2 inline-flex items-center gap-1.5 text-xs font-medium text-danger">
                  <WarningOctagon aria-hidden weight="bold" className="size-3.5" />
                  {t("overview.chart.below", { amount: formatMoney(r.after, currency) })}, {formatMonth(r.month, "long")}
                </p>
              )}
            </li>
          );
        })}
      </ol>
      <div className="relative mt-4 h-4 text-xs text-danger" aria-hidden>
        <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${zero}%` }}>
          {t("overview.chart.floor")}
        </span>
      </div>
    </figure>
  );
}

// ---- Commitments by month ---------------------------------------------------------------------------

export interface CommitmentMonth {
  month: string;
  total: number;
  debt: number;
}

/** Each bar is the month's total; the accent segment inside it is the debt part. No subtraction in the UI. */
export function CommitmentBars({ months, currency }: { months: CommitmentMonth[]; currency: string }) {
  const max = Math.max(...months.map((m) => m.total), 1);
  return (
    <figure aria-labelledby="commit-chart-title" className="min-w-0">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h2 id="commit-chart-title" className="text-lg font-semibold text-ink">
            {t("commitments.chart.title")}
          </h2>
          <p className="mt-0.5 text-sm text-ink-3">{t("commitments.chart.subtitle", { currency })}</p>
        </div>
        <ul className="flex gap-5" aria-label="Legend">
          <LegendItem label={t("commitments.chart.debt")} sample="swatch-focus" />
          <LegendItem label={t("commitments.chart.fixed")} sample="swatch-context" />
        </ul>
      </div>
      <ol className="mt-6 grid grid-flow-col auto-cols-fr items-end gap-2 border-b border-control/60">
        {months.map((m) => (
          <li key={m.month} className="flex flex-col items-center">
            <span className="sr-only">
              {t("commitments.chart.summary", { month: formatMonth(m.month, "long"), total: moneyForSpeech(m.total, currency), debt: moneyForSpeech(m.debt, currency) })}
            </span>
            <span aria-hidden className="num mb-2 text-center text-[11px] leading-tight font-medium text-ink sm:text-xs">
              {formatMoney(m.total, currency)}
            </span>
            <div aria-hidden className="flex h-40 w-6 flex-col justify-end">
              <div
                className="flex w-full flex-col justify-end overflow-hidden rounded-t-[4px] bg-[var(--series-context)]/45"
                style={{ height: `${(m.total / max) * 100}%` }}
              >
                <div className="w-full border-t-2 border-surface bg-[var(--series-focus)]" style={{ height: `${(m.debt / m.total) * 100}%` }} />
              </div>
            </div>
          </li>
        ))}
      </ol>
      <ol aria-hidden className="mt-2 grid grid-flow-col auto-cols-fr gap-2 text-center text-xs text-ink-3">
        {months.map((m) => (
          <li key={m.month}>{formatMonth(m.month)}</li>
        ))}
      </ol>
      <DataTable caption={t("commitments.chart.title")}>
        <thead>
          <tr className="border-b border-line text-left text-xs text-ink-3">
            <th scope="col" className="py-2 pr-4 font-medium">
              {t("common.month")}
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">
              {t("commitments.table.amount")} ({currency})
            </th>
            <th scope="col" className="py-2 text-right font-medium">
              {t("commitments.chart.debt")} ({currency})
            </th>
          </tr>
        </thead>
        <tbody>
          {months.map((m) => (
            <tr key={m.month} className="border-b border-line last:border-0">
              <th scope="row" className="py-2 pr-4 text-left font-normal text-ink-2">
                {formatMonth(m.month)}
              </th>
              <td className="num py-2 pr-4 text-right">{formatAmount(m.total, currency)}</td>
              <td className="num py-2 text-right">{formatAmount(m.debt, currency)}</td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </figure>
  );
}
