import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/** The design tokens in index.css must keep their promise: WCAG AA for every text/ground pair the app draws. */
const css = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");
const declared = new Map<string, string>();
for (const [, name, value] of css.matchAll(/^\s*(--[a-z0-9-]+):\s*([^;]+);/gim)) {
  if (!declared.has(name!)) declared.set(name!, value!.trim());
}

function token(name: string): string {
  let value = declared.get(name);
  if (value === undefined) throw new Error(`token ${name} is not declared in index.css`);
  for (let hops = 0; value.startsWith("var("); hops++) {
    const next: string | undefined = declared.get(value.slice(4, -1).trim());
    if (next === undefined || hops > 5) throw new Error(`token ${name} does not resolve`);
    value = next;
  }
  return value;
}

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(foreground: string, background: string): number {
  const [a, b] = [luminance(token(foreground)), luminance(token(background))];
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

const TEXT: ReadonlyArray<[string, string]> = [
  ["--text", "--bg-canvas"], ["--text-2", "--bg-canvas"], ["--text-3", "--bg-canvas"],
  ["--text", "--bg-surface"], ["--text-2", "--bg-surface"], ["--text-3", "--bg-surface"],
  ["--text-2", "--bg-rail"], ["--text-3", "--bg-rail"],
  ["--accent", "--bg-surface"], ["--accent", "--bg-canvas"], ["--accent", "--accent-soft"],
  ["--on-accent", "--accent"], ["--on-accent", "--accent-hover"],
  ["--positive", "--positive-bg"], ["--warning", "--warning-bg"], ["--danger", "--danger-bg"],
  ["--text-3", "--positive-bg"], ["--text-3", "--danger-bg"],
  ["--rail-text", "--rail-bg"], ["--rail-text-2", "--rail-bg"], ["--rail-text-3", "--rail-bg"],
];
const NON_TEXT: ReadonlyArray<[string, string]> = [
  ["--border-control", "--bg-surface"], ["--series-context", "--bg-surface"], ["--series-context", "--positive-bg"],
  ["--rail-accent", "--rail-bg"],
];

describe("design tokens", () => {
  it.each(TEXT)("%s on %s reaches 4.5:1", (fg, bg) => {
    expect(ratio(fg, bg)).toBeGreaterThanOrEqual(4.5);
  });
  it.each(NON_TEXT)("%s on %s reaches 3:1", (fg, bg) => {
    expect(ratio(fg, bg)).toBeGreaterThanOrEqual(3);
  });
});
