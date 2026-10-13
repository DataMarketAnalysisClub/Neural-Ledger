/**
 * Motion policy. Motion conveys state only. Never animated: money counting up, timer digits,
 * block alerts, success celebrations. Everything respects prefers-reduced-motion.
 */
export function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return true;
  }
}

export function shouldAnimate(): boolean {
  return !prefersReducedMotion();
}
