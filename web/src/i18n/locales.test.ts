import { describe, expect, it } from "vitest";
import { en } from "./en";
import { es } from "./es";
import { zh } from "./zh";

/** Every leaf string with its path: "overview.goal.title" -> "Goal: {name}". */
function leaves(node: unknown, path = ""): [string, string][] {
  if (typeof node === "string") return [[path, node]];
  if (Array.isArray(node)) return node.flatMap((item, i) => leaves(item, `${path}[${i}]`));
  return Object.entries(node as Record<string, unknown>).flatMap(([key, value]) => leaves(value, path ? `${path}.${key}` : key));
}

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe.each([
  ["es", es],
  ["zh", zh],
])("%s", (_, messages) => {
  // The shape is checked by the type (Messages); the {placeholders} are not, and a lost one shows as raw text.
  it("keeps every placeholder of the English text", () => {
    const translated = new Map(leaves(messages));
    for (const [path, text] of leaves(en)) expect(placeholders(translated.get(path) ?? ""), path).toEqual(placeholders(text));
  });
});
