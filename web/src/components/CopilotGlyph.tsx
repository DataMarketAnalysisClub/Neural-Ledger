import type { ReactNode } from "react";
import { cn } from "@/components/ui";

/** What a nav icon takes: Phosphor icons and this glyph both fit. */
export type NavIcon = (props: { className?: string; weight?: "regular" | "fill"; "aria-hidden"?: boolean | "true" | "false" }) => ReactNode;

/**
 * The Copilot's nav icon: the silhouette of the brand mark's N, extra heavy, so it holds its own next to the
 * outlined icons. It takes `currentColor`, like they do; `weight` is accepted so it fits the same slot, and the
 * shape is the same in both (the sidebar tints the current one).
 */
export function CopilotGlyph({ className }: { weight?: "regular" | "fill"; className?: string; "aria-hidden"?: boolean | "true" | "false" }) {
  return (
    <svg aria-hidden="true" data-glyph="copilot" viewBox="0 0 256 256" fill="currentColor" stroke="currentColor" strokeWidth={14} strokeLinejoin="round" className={cn("shrink-0", className)}>
      <rect x="32" y="36" width="52" height="184" />
      <rect x="172" y="36" width="52" height="184" />
      <polygon points="32,36 90,36 224,220 166,220" />
    </svg>
  );
}
