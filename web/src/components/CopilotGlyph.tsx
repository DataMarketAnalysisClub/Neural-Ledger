import type { ReactNode } from "react";
import { cn } from "@/components/ui";

/** What a nav icon takes: Phosphor icons and this glyph both fit. */
export type NavIcon = (props: { className?: string; weight?: "regular" | "fill"; "aria-hidden"?: boolean | "true" | "false" }) => ReactNode;

/**
 * The Copilot's nav icon: the brand mark drawn as a line glyph, so it sits with the other icons (same grid, same
 * stroke, `currentColor`). `weight` follows Phosphor's: regular, and fill (a heavier stroke) when it is the
 * current screen.
 */
export function CopilotGlyph({ weight = "regular", className }: { weight?: "regular" | "fill"; className?: string; "aria-hidden"?: boolean | "true" | "false" }) {
  const stroke = weight === "fill" ? 24 : 16;
  return (
    <svg aria-hidden="true" data-glyph="copilot" viewBox="0 0 256 256" fill="none" stroke="currentColor" strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" className={cn("shrink-0", className)}>
      <path d="M44 176V48l168 128V48" />
      <path d="M44 224h104" strokeDasharray="1 31" />
      <circle cx="212" cy="224" r="15" fill="currentColor" stroke="none" />
    </svg>
  );
}
