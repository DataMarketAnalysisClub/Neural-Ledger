import { describe, expect, it } from "vitest";
import { isObsolete, mergeCounters } from "./counters";

const at = (consent_generation: number, memory_revision: number) => ({ consent_generation, memory_revision });

describe("memory counters", () => {
  it("keep the largest of each counter, whatever order the responses arrive in", () => {
    const responses = [at(1, 0), at(2, 3), at(1, 4), at(2, 1)];
    for (const order of [responses, [...responses].reverse(), [responses[2], responses[0], responses[3], responses[1]]]) {
      expect(order.reduce(mergeCounters, null)).toEqual(at(2, 4));
    }
  });

  it("never go back for a late response, nor for a missing one", () => {
    expect(mergeCounters(at(3, 2), at(1, 1))).toEqual(at(3, 2));
    expect(mergeCounters(at(3, 2), null)).toEqual(at(3, 2));
    expect(mergeCounters(null, null)).toBeNull();
  });

  it("make a dependency obsolete once either counter grew past it", () => {
    expect(isObsolete(at(1, 1), at(1, 1))).toBe(false);
    expect(isObsolete(at(1, 1), at(2, 1))).toBe(true); // revoked (or consented again)
    expect(isObsolete(at(1, 1), at(1, 2))).toBe(true); // a declaration confirmed or deleted
    expect(isObsolete(at(2, 5), at(1, 4))).toBe(false); // the tab is behind: it never hides a newer reply
  });

  it("hide nothing that did not rely on memory, and nothing before any counter is known", () => {
    expect(isObsolete(null, at(9, 9))).toBe(false);
    expect(isObsolete(at(1, 1), null)).toBe(false);
  });
});
