/**
 * The liquidity bridge: today's balance stepping down, payday cycle by payday cycle, to the lowest
 * point before payday, then minus the safety floor, to what is protected. Every value shown is an
 * engine fact; the component only positions them. This is the product's signature view.
 */
import { useEffect, useState } from "react";
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
  | { kind: "total"; id: string; label: string; value: number; from: number; to: number; tone: "ink" | "accent" | "danger" }
  | { kind: "step"; id: string; label: string; value: number; from: number; to: number; tone: "flow" | "floor" };

export function LiquidityBridge(props: BridgeProps) {
  const { currency, balance, cycles, floor, protectedSurplus, bindingMonth } = props;
  const low = cycles.at(-1)?.trough ?? balance;

  const columns: Column[] = [
    { kind: "total", id: "balance", label: t("overview.bridge.balance"), value: balance, from: 0, to: balance, tone: "ink" },
    ...cycles.map<Column>((c, i) => ({
      kind: "step",
      id: c.month,
      label: t("overview.bridge.cashFlow", { month: formatMonth(c.month) }),
      value: c.available,
      from: i === 0 ? balance : (cycles[i - 1]?.trough ?? balance),
      to: c.trough,
      tone: "flow",
    })),
    {
      kind: "total",
      id: "low",
      label: t("overview.bridge.lowPoint", { month: formatMonth(bindingMonth) }),
      value: low,
      from: 0,
      to: low,
      tone: "ink",
    },
    { kind: "step", id: "floor", label: t("overview.bridge.floor"), value: -floor, from: low, to: protectedSurplus, tone: "floor" },
  ];

  // Geometry only: the vertical scale spans every level the engine reported, including zero.
  const levels = [0, ...columns.flatMap((c) => [c.from, c.to]), protectedSurplus];
  const top = Math.max(...levels);
  const bottom = Math.min(...levels);
  const span = top - bottom || 1;
  const y = (v: number) => ((top - v) / span) * 100; // % from the top of the plot
  const zeroY = y(0);

  const [entered, setEntered] = useState(!shouldAnimate());
  useEffect(() => {
    if (entered) return;
    const id = requestAnimationFrame(() => setEntered(true));
    return () => cancelAnimationFrame(id);
  }, [entered]);

  const negative = protectedSurplus < 0;
  const factFor = (key: string) => props.facts?.find((f) => f.key === key);
  const prov = (key?: string): ProvenanceInfo => ({ fact: key ? factFor(key) : undefined, snapshotId: props.snapshotId, paramsVersion: props.paramsVersion });

  return (
    <figure aria-labelledby="bridge-title" className="grid gap-8 lg:grid-cols-[minmax(240px,300px)_1fr] lg:gap-12">
      <div className="flex flex-col justify-between gap-6">
        <div>
          <p id="bridge-title" className="text-sm font-medium text-ink-2">
            {negative ? t("overview.bridge.shortfall") : t("overview.bridge.protected")}
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
        <figcaption className="text-xs text-ink-3">{t("overview.bridge.caption")}</figcaption>
      </div>

      <div className="min-w-0">
      <p className="mb-3 text-right text-xs text-ink-3">{t("overview.bridge.unit", { currency })}</p>
      <ol aria-label={t("overview.bridge.label")} className="grid min-w-0 auto-cols-fr grid-flow-col gap-2 sm:gap-3">
        {columns.map((col, index) => {
          const barTop = y(Math.max(col.from, col.to));
          const barHeight = Math.max(Math.abs(y(col.from) - y(col.to)), 0.6);
          const isFloor = col.kind === "step" && col.tone === "floor";
          const fill =
            col.kind === "total"
              ? col.tone === "ink"
                ? "bg-ink"
                : "bg-accent"
              : isFloor
                ? "bg-danger-bg border border-danger/60 [background-image:repeating-linear-gradient(135deg,transparent_0_5px,rgb(180_35_24/0.22)_5px_6px)]"
                : col.value < 0
                  ? "bg-[var(--series-context)]"
                  : "bg-positive";
          const next = columns[index + 1];
          return (
            <li key={col.id} className="flex min-w-0 flex-col">
              <div className="relative h-44 sm:h-52" aria-hidden>
                {/* zero baseline */}
                <div className="absolute inset-x-0 border-t border-control/50" style={{ top: `${zeroY}%` }} />
                <div
                  className={cn(
                    "absolute inset-x-[14%] rounded-[3px] transition-[opacity,transform] duration-300 ease-out",
                    fill,
                    entered ? "translate-y-0 opacity-100" : "translate-y-1.5 opacity-0",
                  )}
                  style={{ top: `${barTop}%`, height: `${barHeight}%`, transitionDelay: entered ? `${index * 60}ms` : "0ms" }}
                />
                {/* connector to the next column at the running level */}
                {next && (
                  <div
                    className="absolute right-[-14%] left-[86%] border-t border-dashed border-control"
                    style={{ top: `${y(col.to)}%` }}
                  />
                )}
              </div>
              <div className="mt-3 min-w-0 border-t border-line pt-2">
                <p className="text-xs leading-snug text-ink-3">{col.label}</p>
                <p
                  className={cn("num mt-1 text-sm font-medium", isFloor ? "text-danger" : col.value < 0 ? "text-ink" : "text-ink")}
                  aria-label={`${col.label}: ${moneyForSpeech(col.value, currency)}`}
                >
                  {formatAmount(col.value, currency, { signed: col.kind === "step" })}
                </p>
              </div>
            </li>
          );
        })}
        <li className="flex min-w-0 flex-col">
          <div className="relative h-44 sm:h-52" aria-hidden>
            <div className="absolute inset-x-0 border-t border-control/50" style={{ top: `${zeroY}%` }} />
            <div
              className={cn(
                "absolute inset-x-[14%] rounded-[3px] transition-[opacity,transform] duration-300 ease-out",
                negative ? "bg-danger" : "bg-accent",
                entered ? "translate-y-0 opacity-100" : "translate-y-1.5 opacity-0",
              )}
              style={{
                top: `${y(Math.max(0, protectedSurplus))}%`,
                height: `${Math.max(Math.abs(y(0) - y(protectedSurplus)), 0.8)}%`,
                transitionDelay: entered ? `${columns.length * 60}ms` : "0ms",
              }}
            />
          </div>
          <div className="mt-3 min-w-0 border-t border-ink pt-2">
            <p className="text-xs leading-snug font-medium text-ink">{negative ? t("overview.bridge.shortfall") : t("overview.bridge.protected")}</p>
            <p className={cn("num mt-1 text-sm font-semibold", negative ? "text-danger" : "text-accent")}>{formatAmount(protectedSurplus, currency)}</p>
          </div>
        </li>
      </ol>
      </div>
    </figure>
  );
}
