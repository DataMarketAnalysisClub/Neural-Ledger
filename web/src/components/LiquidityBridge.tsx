/**
 * The liquidity bridge: today's balance stepping down, payday cycle by payday cycle, to the lowest
 * point before payday, then minus the safety floor, to what is protected. Every value shown is an
 * engine fact; the component only positions them. This is the product's signature view.
 */
import { useEffect, useState } from "react";
import { CheckCircle, Prohibit } from "@phosphor-icons/react";
import type { Fact } from "@/api/client";
import { formatAmount, formatMoney, formatMonth, moneyForSpeech } from "@/lib/format";
import { shouldAnimate } from "@/lib/motion";
import { t } from "@/i18n";
import { cn, Money, type ProvenanceInfo } from "./ui";

export interface BridgeCycle {
  month: string;
  available: number; // the cycle's cash flow, from the engine
  trough: number; // the running balance just before payday, from the engine
}

export interface BridgeProps {
  currency: string;
  balance: number; // opening trough (checking today)
  cycles: BridgeCycle[]; // up to and including the binding month
  floor: number;
  protectedSurplus: number; // headroom in the binding month
  bindingMonth: string;
  snapshotId?: string | null;
  paramsVersion?: string;
  facts?: Fact[];
}

type Column =
  | { kind: "total"; id: string; label: string; value: number; from: number; to: number }
  | { kind: "step"; id: string; label: string; value: number; from: number; to: number; tone: "flow" | "floor" };

export function LiquidityBridge(props: BridgeProps) {
  const { currency, balance, cycles, floor, protectedSurplus, bindingMonth } = props;
  const low = cycles.at(-1)?.trough ?? balance;

  const columns: Column[] = [
    { kind: "total", id: "balance", label: t("overview.bridge.balance"), value: balance, from: 0, to: balance },
    ...cycles.map<Column>((c, i) => ({
      kind: "step",
      id: c.month,
      label: t("overview.bridge.cashFlow", { month: formatMonth(c.month) }),
      value: c.available,
      from: i === 0 ? balance : (cycles[i - 1]?.trough ?? balance),
      to: c.trough,
      tone: "flow",
    })),
    { kind: "total", id: "low", label: t("overview.bridge.lowPoint", { month: formatMonth(bindingMonth) }), value: low, from: 0, to: low },
    { kind: "step", id: "floor", label: t("overview.bridge.floor"), value: -floor, from: low, to: protectedSurplus, tone: "floor" },
  ];

  // Geometry only: the scale spans every level the engine reported, including zero.
  const levels = [0, ...columns.flatMap((c) => [c.from, c.to]), protectedSurplus];
  const top = Math.max(...levels);
  const bottom = Math.min(...levels);
  const span = top - bottom || 1;
  const y = (v: number) => ((top - v) / span) * 100; // % from the top (waterfall)
  const x = (v: number) => ((v - bottom) / span) * 100; // % from the left (rows)
  const zeroY = y(0);
  const zeroX = x(0);

  const [entered, setEntered] = useState(!shouldAnimate());
  useEffect(() => {
    if (entered) return;
    const id = requestAnimationFrame(() => setEntered(true));
    return () => cancelAnimationFrame(id);
  }, [entered]);
  const enter = (index: number) => ({
    className: cn("transition-[opacity,transform] duration-300 ease-out", entered ? "translate-y-0 opacity-100" : "translate-y-1.5 opacity-0"),
    delay: entered ? `${index * 60}ms` : "0ms",
  });

  const negative = protectedSurplus < 0;
  const TotalIcon = negative ? Prohibit : CheckCircle;
  const totalLabel = negative ? t("overview.bridge.shortfall") : t("overview.bridge.protected");
  const totalText = negative ? "text-danger" : "text-positive";
  const totalFill = negative ? "bg-danger" : "bg-positive";
  const factFor = (key: string) => props.facts?.find((f) => f.key === key);
  const prov = (key?: string): ProvenanceInfo => ({ fact: key ? factFor(key) : undefined, snapshotId: props.snapshotId, paramsVersion: props.paramsVersion });

  const fillFor = (col: Column) =>
    col.kind === "total"
      ? "bg-ink"
      : col.tone === "floor"
        ? "bg-danger-bg border border-danger/60 [background-image:repeating-linear-gradient(135deg,transparent_0_5px,var(--danger-hatch)_5px_6px)]"
        : col.value < 0
          ? "bg-[var(--series-context)]"
          : "bg-positive";
  const valueClass = (col: Column) => (col.kind === "step" && col.tone === "floor" ? "text-danger" : "text-ink");

  return (
    <figure aria-labelledby="bridge-title" className="grid gap-8 lg:grid-cols-[minmax(240px,300px)_1fr] lg:gap-12">
      <div className="flex flex-col justify-between gap-6">
        <div>
          <p id="bridge-title" className={cn("flex items-center gap-1.5 text-sm font-medium", totalText)}>
            <TotalIcon aria-hidden weight="bold" className="size-4" />
            {totalLabel}
          </p>
          {/* The ISO code sits above the figure so long amounts never overflow the column. */}
          <p className={cn("mt-2 font-semibold", negative ? "text-danger" : "text-ink")}>
            <span className="block text-lg tracking-normal text-ink-2">{currency}</span>
            <span className="block text-[clamp(2.25rem,4.2vw,3.5rem)] leading-none tracking-[-0.035em]">
              <Money amount={protectedSurplus} currency={currency} provenance={prov("protected_surplus")} bare />
            </span>
          </p>
          <p className="mt-3 text-sm text-ink-2">
            {t("overview.chart.summary", {
              amount: formatMoney(low, currency),
              month: formatMonth(bindingMonth, "long"),
              floor: formatMoney(floor, currency),
            })}
          </p>
        </div>
        <figcaption className="text-xs text-ink-3">{negative ? t("overview.bridge.captionShort") : t("overview.bridge.caption")}</figcaption>
      </div>

      <div className="min-w-0">
        <p className="mb-3 text-right text-xs text-ink-3">{t("overview.bridge.unit", { currency })}</p>

        {/* Narrow screens: one row per step on a shared horizontal axis, so every step stays in view. */}
        <ol aria-label={t("overview.bridge.label")} className="space-y-2.5 sm:hidden">
          {columns.map((col, index) => {
            const motion = enter(index);
            return (
              <li key={col.id} className="grid grid-cols-[minmax(0,7.5rem)_1fr_auto] items-center gap-3">
                <span className="text-xs leading-snug text-ink-3">{col.label}</span>
                <span aria-hidden className="relative h-3">
                  <span className="absolute inset-y-[-3px] w-px bg-control/60" style={{ left: `${zeroX}%` }} />
                  <span
                    className={cn("absolute inset-y-0 rounded-[2px]", fillFor(col), motion.className)}
                    style={{
                      left: `${x(Math.min(col.from, col.to))}%`,
                      width: `${Math.max(Math.abs(x(col.from) - x(col.to)), 0.8)}%`,
                      transitionDelay: motion.delay,
                    }}
                  />
                </span>
                <span className={cn("num text-right text-sm font-medium", valueClass(col))} aria-label={`${col.label}: ${moneyForSpeech(col.value, currency)}`}>
                  {formatAmount(col.value, currency, { signed: col.kind === "step" })}
                </span>
              </li>
            );
          })}
          <li className="grid grid-cols-[minmax(0,7.5rem)_1fr_auto] items-center gap-3 border-t border-ink pt-2.5">
            <span className={cn("flex items-center gap-1 text-xs font-medium", totalText)}>
              <TotalIcon aria-hidden weight="bold" className="size-3.5 shrink-0" />
              {totalLabel}
            </span>
            <span aria-hidden className="relative h-3">
              <span className="absolute inset-y-[-3px] w-px bg-control/60" style={{ left: `${zeroX}%` }} />
              <span
                className={cn("absolute inset-y-0 rounded-[2px]", totalFill)}
                style={{ left: `${x(Math.min(0, protectedSurplus))}%`, width: `${Math.max(Math.abs(x(protectedSurplus) - zeroX), 0.8)}%` }}
              />
            </span>
            <span className={cn("num text-right text-sm font-semibold", totalText)}>{formatAmount(protectedSurplus, currency)}</span>
          </li>
        </ol>

        {/* Wider screens: the waterfall, one column per step. */}
        <ol aria-label={t("overview.bridge.label")} className="hidden auto-cols-fr grid-flow-col gap-2 sm:grid sm:gap-3">
          {columns.map((col, index) => {
            const next = columns[index + 1];
            const motion = enter(index);
            return (
              <li key={col.id} className="flex min-w-0 flex-col">
                <div className="relative h-52" aria-hidden>
                  <div className="absolute inset-x-0 border-t border-control/50" style={{ top: `${zeroY}%` }} />
                  <div
                    className={cn("absolute inset-x-[14%] rounded-[3px]", fillFor(col), motion.className)}
                    style={{
                      top: `${y(Math.max(col.from, col.to))}%`,
                      height: `${Math.max(Math.abs(y(col.from) - y(col.to)), 0.6)}%`,
                      transitionDelay: motion.delay,
                    }}
                  />
                  {/* connector to the next column at the running level */}
                  {next && <div className="absolute right-[-14%] left-[86%] border-t border-dashed border-control" style={{ top: `${y(col.to)}%` }} />}
                </div>
                <div className="mt-3 min-w-0 border-t border-line pt-2">
                  <p className="text-xs leading-snug text-ink-3">{col.label}</p>
                  <p className={cn("num mt-1 text-sm font-medium", valueClass(col))} aria-label={`${col.label}: ${moneyForSpeech(col.value, currency)}`}>
                    {formatAmount(col.value, currency, { signed: col.kind === "step" })}
                  </p>
                </div>
              </li>
            );
          })}
          <li className="flex min-w-0 flex-col">
            <div className="relative h-52" aria-hidden>
              <div className="absolute inset-x-0 border-t border-control/50" style={{ top: `${zeroY}%` }} />
              <div
                className={cn("absolute inset-x-[14%] rounded-[3px]", totalFill, enter(columns.length).className)}
                style={{
                  top: `${y(Math.max(0, protectedSurplus))}%`,
                  height: `${Math.max(Math.abs(y(0) - y(protectedSurplus)), 0.8)}%`,
                  transitionDelay: enter(columns.length).delay,
                }}
              />
            </div>
            <div className="mt-3 min-w-0 border-t border-ink pt-2">
              <p className={cn("flex items-center gap-1 text-xs leading-snug font-medium", totalText)}>
                <TotalIcon aria-hidden weight="bold" className="size-3.5 shrink-0" />
                {totalLabel}
              </p>
              <p className={cn("num mt-1 text-sm font-semibold", totalText)}>{formatAmount(protectedSurplus, currency)}</p>
            </div>
          </li>
        </ol>
      </div>
    </figure>
  );
}
