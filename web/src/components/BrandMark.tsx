import { cn } from "@/components/ui";

/**
 * The product mark: an N built from the bridge's steps, over the dashed safety floor, with the accent point the
 * user signs. Its roles default to the dark rail's (a light tile, a dark N); on another ground pass the colors.
 */
export function BrandMark({ className, tile = "var(--text)", ink = "var(--bg-rail)", dot = "var(--accent)" }: { className?: string; tile?: string; ink?: string; dot?: string }) {
  return (
    <svg aria-hidden viewBox="0 0 64 64" className={cn("size-8 shrink-0", className)}>
      <rect width="64" height="64" rx="14" fill={tile} />
      <g fill={ink}>
        <rect x="16" y="14" width="7" height="32" />
        <rect x="41" y="14" width="7" height="32" />
        <polygon points="16,14 23,14 48,46 41,46" />
      </g>
      <line x1="14" y1="53" x2="40" y2="53" stroke={ink} strokeOpacity="0.55" strokeWidth="2.5" strokeDasharray="6 3" />
      <circle cx="49.5" cy="53" r="4.5" fill={dot} />
    </svg>
  );
}
