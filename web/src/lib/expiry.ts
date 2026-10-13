/**
 * Countdowns driven by the API's expires_at, measured on the API's clock (from /health server_time,
 * which is fixed in recorded demos), never by a hard-coded duration.
 */
import { useEffect, useState } from "react";
import { useHealth } from "@/api/hooks";

/** Milliseconds to add to Date.now() to get the API's notion of "now". */
export function useServerSkew(): number {
  const health = useHealth();
  const serverTime = health.data?.server_time;
  if (!serverTime || !health.dataUpdatedAt) return 0;
  const parsed = Date.parse(serverTime);
  return Number.isNaN(parsed) ? 0 : parsed - health.dataUpdatedAt;
}

export interface Countdown {
  remainingMs: number;
  expired: boolean;
  label: string; // "29:41"
  /** Announce only at thresholds, never every tick. */
  threshold: "5min" | "1min" | "expired" | null;
}

export function formatRemaining(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function useCountdown(expiresAt: string | null | undefined): Countdown | null {
  const skew = useServerSkew();
  const [now, setNow] = useState(() => Date.now());
  const target = expiresAt ? Date.parse(expiresAt) : NaN;
  const remaining = Number.isNaN(target) ? 0 : target - (now + skew);
  const lastMinute = remaining <= 60_000;

  useEffect(() => {
    if (Number.isNaN(target)) return;
    // Every 15 s until the last minute, then every second.
    const id = window.setInterval(() => setNow(Date.now()), lastMinute ? 1_000 : 15_000);
    return () => window.clearInterval(id);
  }, [target, lastMinute]);

  if (!expiresAt || Number.isNaN(target)) return null;
  const expired = remaining <= 0;
  const threshold = expired ? "expired" : remaining <= 60_000 ? "1min" : remaining <= 5 * 60_000 ? "5min" : null;
  const label = remaining > 60_000 ? `${Math.ceil(remaining / 60_000)} min` : formatRemaining(remaining);
  return { remainingMs: remaining, expired, label, threshold };
}
