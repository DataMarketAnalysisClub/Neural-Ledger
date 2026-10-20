/**
 * The memory counters (ADR-048 §6, memory_consent): consent_generation and memory_revision only ever grow on the
 * server. A tab keeps the largest of each it has seen, from any response, so a response that arrives late or out of
 * order never takes them back. A reply or card that relied on memory carries the counters it read; once the tab has
 * seen either counter grow past them, everything built on that memory is obsolete and is hidden whole.
 */
export interface MemoryCounters {
  readonly consent_generation: number;
  readonly memory_revision: number;
}

/** The larger of each counter. Never smaller than what was known, whatever order the responses arrive in. */
export function mergeCounters(known: MemoryCounters | null | undefined, seen: MemoryCounters | null | undefined): MemoryCounters | null {
  if (!seen) return known ?? null;
  if (!known) return { consent_generation: seen.consent_generation, memory_revision: seen.memory_revision };
  return {
    consent_generation: Math.max(known.consent_generation, seen.consent_generation),
    memory_revision: Math.max(known.memory_revision, seen.memory_revision),
  };
}

/** True when the tab knows memory moved after `dependency` was read. No dependency: nothing relied on memory. */
export function isObsolete(dependency: MemoryCounters | null | undefined, known: MemoryCounters | null | undefined): boolean {
  if (!dependency || !known) return false;
  return known.consent_generation > dependency.consent_generation || known.memory_revision > dependency.memory_revision;
}
