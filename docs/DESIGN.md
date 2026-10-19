---
name: Neural Ledger
description: AI cash-flow copilot. The engine states facts in tabular figures, the copilot interprets in prose, and the user alone signs.
colors:
  cool-canvas: "#f2f7f6"
  work-surface: "#ffffff"
  rail-gray: "#e6efed"
  hairline: "#d8e5e3"
  control-stroke: "#7d8796"
  context-gray: "#5f7f7c"
  ink: "#14181f"
  ink-2: "#4a5361"
  ink-3: "#5f6875"
  teal: "#0f766e"
  teal-deep: "#115e59"
  teal-wash: "#e0f2f0"
  rail-ink: "#0b2f2e"
  rail-text: "#f2f7f6"
  rail-accent: "#5eead4"
  protected-green: "#0e7a4f"
  protected-green-wash: "#eaf5ef"
  caution-amber: "#9a5800"
  caution-amber-wash: "#fff4e0"
  breach-red: "#b42318"
  breach-red-wash: "#fef0ee"
typography:
  hero:
    fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(2.25rem, 4.2vw, 3.5rem)"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.035em"
    fontFeature: "\"tnum\" 1"
  headline:
    fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "2rem"
    fontWeight: 600
    lineHeight: "2.5rem"
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: "1.75rem"
    letterSpacing: "-0.02em"
  figure:
    fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: "2rem"
    letterSpacing: "-0.02em"
    fontFeature: "\"tnum\" 1"
  body:
    fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.55
  body-sm:
    fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: "1.375rem"
  label:
    fontFamily: "Geist, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: "1.25rem"
  code:
    fontFamily: "Geist Mono, ui-monospace, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: "1.25rem"
rounded:
  control: "6px"
  object: "10px"
  pill: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  2xl: "40px"
components:
  button-primary:
    backgroundColor: "{colors.teal}"
    textColor: "{colors.work-surface}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.teal-deep}"
  button-secondary:
    backgroundColor: "{colors.work-surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "40px"
  button-secondary-hover:
    backgroundColor: "{colors.cool-canvas}"
  button-quiet:
    textColor: "{colors.ink-2}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "32px"
  button-quiet-hover:
    backgroundColor: "{colors.rail-gray}"
    textColor: "{colors.ink}"
  button-danger:
    backgroundColor: "{colors.breach-red}"
    textColor: "{colors.work-surface}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "40px"
  input:
    backgroundColor: "{colors.work-surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "40px"
  surface:
    backgroundColor: "{colors.work-surface}"
    rounded: "{rounded.control}"
  receipt:
    backgroundColor: "{colors.work-surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.object}"
    padding: "24px"
  badge-positive:
    backgroundColor: "{colors.protected-green-wash}"
    textColor: "{colors.protected-green}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
  badge-warning:
    backgroundColor: "{colors.caution-amber-wash}"
    textColor: "{colors.caution-amber}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
  badge-danger:
    backgroundColor: "{colors.breach-red-wash}"
    textColor: "{colors.breach-red}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
  nav-item:
    textColor: "{colors.ink-2}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "40px"
  nav-item-active:
    backgroundColor: "{colors.work-surface}"
    textColor: "{colors.ink}"
  chat-user:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.work-surface}"
    rounded: "{rounded.control}"
    padding: "12px 16px"
  chat-copilot:
    backgroundColor: "{colors.cool-canvas}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "12px 16px"
---

# Design System: Neural Ledger

Direction pinned by user (minimalist, flat surfaces, teal on cool neutrals); no concept roll. Recorded from the shipped build in `web/src` (tokens in `web/src/index.css`), mode Operate, code-led.

## Overview

**Creative North Star: "The Signed Ledger"**

Two voices share one screen. The engine states facts in tabular figures; the copilot interprets them in prose; only the user signs. The system makes that division visible: numbers are set in ink with tabular figures and carry their ISO code and provenance, the copilot's prose sits in a softer bordered bubble, and the one thing that gains weight, depth and a seal is the receipt the user confirms.

The ground is a cool neutral canvas with white work surfaces separated by 1px hairlines, and a dark rail (ink teal) that holds the brand and the navigation. Everything is flat at rest. Teal is rare by design: it appears only where the user can act, where focus is, what is selected, and which step is current. Data is drawn in ink and gray, never in the accent, so the accent never competes with a figure. Status colors exist only as states and never travel without an icon and words.

Density is that of a working tool: a fixed rem type scale, 6px corners, sections separated by space and rules rather than nested cards. The interface refuses the fintech default of three equal KPI tiles and a chat that looks like it decides.

**Key Characteristics:**
- Cool neutral canvas, white surfaces, 1px hairlines; flat at rest.
- Teal only for action, focus, selection and the current step.
- Ink for the data that matters, gray for context; status color only with icon and words.
- Geist throughout with tabular figures; Geist Mono only for hashes, ids and codes.
- Every amount carries its ISO code: `CLP 1,500,000`.
- Signature: the liquidity bridge. Second moment: the receipt that seals on confirmation.

## Colors

A three-layer palette (primitives, semantic roles, component tokens in `web/src/index.css`): cool grays, one teal, and three state hues. Components consume only semantic roles, never primitives.

### Primary
- **Teal** (teal): primary buttons, focus outline (2px, offset 2px), caret, text selection wash (15% teal), the current step in the receipt stepper, the active nav icon. White on teal measures 5.47:1.
- **Deep Teal** (teal-deep): hover state of teal actions (white on it 7.58:1).
- **Teal Wash** (teal-wash): the copilot reply bubble (with a 3px teal edge, so the interpreting voice reads apart from the engine's figures) and the accent tone of badges and notices; teal text on it 4.72:1.

### Neutral
- **Cool Canvas** (cool-canvas): page ground, secondary-button hover, segmented-control track.
- **Work Surface** (work-surface): cards, inputs, receipt, popovers, the selected segment or nav item.
- **Rail Gray** (rail-gray): skeletons, neutral badges, quiet-button hover.
- **Rail Ink** (rail-ink): the dark rail, the sidebar from `lg` and the header on a phone. Inside it the semantic roles are remapped (`.rail` in `web/src/index.css`): rail-text 13.29:1, mist text 9.85:1 and 6.95:1, rail-accent (the active icon and the mark's point) 9.72:1.
- **Hairline** (hairline): every 1px rule and container border; chart gridlines.
- **Control Stroke** (control-stroke): input and secondary-button borders, the zero axis, connectors (3.63:1 on white, non-text only).
- **Ink** (ink): primary text, the focus data series, bridge totals, completed steps, the user's chat bubble. 17.79:1 on white.
- **Ink 2** (ink-2): secondary text (7.77:1 on white, 6.64:1 on rail gray).
- **Ink 3** (ink-3): tertiary text, captions, axis labels (5.64:1 on white, 4.82:1 on rail gray).
- **Context Gray** (context-gray, a sea gray; 4.36:1 on white, non-text only): the context data series and negative cash-flow steps in the bridge only; never text.

### Tertiary (states only)
- **Protected Green** (protected-green): protected / verified / on track (5.36:1 on white, 4.80:1 on its wash).
- **Caution Amber** (caution-amber): clarification needed, validity nearing expiry (5.11:1 on its wash).
- **Breach Red** (breach-red): the safety floor line, breaches, refusals, expired terms, field errors (6.57:1 on white, 5.92:1 on its wash).
- Each state hue has a wash (protected-green-wash, caution-amber-wash, breach-red-wash) used as the badge and notice ground, and as the ground of the Overview bridge card: green wash when a surplus is protected, red wash when there is a shortfall.

### Named Rules
**The Reserved Accent Rule.** Teal marks action, focus, selection and the current step. It is never a data series, a decorative fill, or a heading color.

**The Ink-Not-Accent Data Rule.** The series that matters is drawn in ink (solid, 2.5px); context is gray and also distinguished by line style (dashed). Text never wears a series color.

**The State-Has-Words Rule.** Green, amber and red appear only as states, and always with an icon and words. Color reinforces meaning; it never carries it alone.

## Typography

**Display Font:** Geist (with ui-sans-serif, system-ui)
**Body Font:** Geist (with ui-sans-serif, system-ui)
**Label/Mono Font:** Geist Mono (with ui-monospace), for hashes, ids and codes only

Both faces are self-hosted from the `geist` package as variable woff2 (weights 100 to 900, `font-display: swap`); no external font host.

**Character:** A single neutral grotesque that reads like a well-set statement: headings tighten slightly, figures sit in fixed-width columns, and the mono face is reserved for machine identifiers so it signals "this is a reference, not a sentence".

### Hierarchy
- **Hero** (600, clamp(2.25rem, 4.2vw, 3.5rem), line-height 1, -0.035em): the protected figure in the liquidity bridge only. Its ISO code sits on its own line above, at title size in ink-2, so long amounts never overflow.
- **Headline** (600, 2rem / 2.5rem): page titles, which state the fact ("December 2026: CLP 20,000 protected of CLP 920,000").
- **Figure** (600, 1.5rem / 2rem): the receipt amount and other standalone money values.
- **Title** (600, 1.25rem / 1.75rem): section and receipt headings.
- **Body** (400, 1rem / 1.55): page subtitles and prose. Copilot replies use 15px with relaxed leading, capped at 65ch.
- **Body small** (400, 0.875rem / 1.375rem): buttons (500), table cells, term rows, notices.
- **Label** (500 or 400, 0.8125rem / 1.25rem): captions, legends, badges, step labels, axis ticks. Sentence case; no uppercase tracking.

The scale is fixed rem (ratio about 1.2) for product UI; only the hero figure is fluid. Headings use `text-wrap: balance` and -0.02em tracking.

### Named Rules
**The Tabular Figures Rule.** Every number is tabular (`font-variant-numeric: tabular-nums`, `"tnum" 1`): any element marked as a number, every table.

**The Mono-Means-Machine Rule.** Geist Mono is used only for hashes, snapshot ids, params versions, reason codes, tool names and audit sequence numbers. Money is never set in mono.

**The ISO Code Rule.** Every amount shows its ISO code before the figure with a real minus sign: `CLP 1,500,000`, `CLP −18,995`, `CLP +260,000`. A figure may drop the code only when its column header or figure group already carries it once (for example "Amounts in CLP" above the bridge); speech output keeps the code. Compact `k` / `M` notation appears only on chart axes, with one unit for every tick of that axis. Months always carry the year ("Dec 2026").

## Layout

- **Shell:** at `lg` (1024px) and up, a 248px sticky dark rail (rail-ink, full viewport height) beside the content column. Below `lg` the rail is replaced by a sticky dark header (brand, the profile on the right, the sandbox seal or the demo persona switch under them) and a fixed bottom bar; see Navigation. Touch targets are at least 44px.
- **Content column:** a thin top bar (sandbox seal, mode, as-of date, right-aligned) above `main`, max width 1280px, padding 24px (40px from `lg`), vertical padding 32px (40px from `lg`).
- **Rhythm:** a 4px base. Common steps are 8, 12, 16, 24 and 32px; page header to content 32px; section heading to content 16px; receipt internal blocks 20 to 24px.
- **Sections** are separated by space and hairlines, not nested cards. A white surface is used for a working object (the bridge, the chat, the receipt, tables), not as a default wrapper for every block.
- **Overview composition:** the bridge spans the full width at the top; a two-column zone below (forecast chart, and a narrow column of monthly cash flow, reserve and goal) separated by a vertical hairline.
- **Breakpoints:** `sm` 640px switches the bridge from rows to the waterfall; `lg` 1024px splits the shell and the bridge's figure column (minmax(240px, 300px)) from its chart.

## Elevation & Depth

Flat by default. Depth is conveyed by ground changes (canvas, white surface, rail) and 1px hairlines. One shadow exists, and it is earned: the confirmed receipt lifts once the user signs, and floating overlays (the provenance popover, the chart tooltip) use the same shadow because they sit above the page.

### Shadow Vocabulary
- **Object** (`box-shadow: 0 1px 2px rgb(20 24 31 / 0.06), 0 8px 24px rgb(20 24 31 / 0.08)`): the receipt in the confirmed and executed states, the provenance popover, the chart tooltip.

### Named Rules
**The Earned Depth Rule.** Nothing is lifted at rest. The receipt gains its shadow (and a stronger ink border) only after confirmation; overlays carry it because they float. No card, button or panel gets a shadow for decoration.

**The Ring-Not-Shadow Selection Rule.** A selected segment or active nav item becomes a white surface with a 1px hairline ring. Selection never uses a shadow or a fill of teal.

## Shapes

Gently squared corners. Controls and containers use 6px (control); 10px (object) is reserved for the receipt being signed and the provenance popover. Pills (full radius) are used for status badges, the sandbox seal, suggestion chips and the seal medallion. Inner segments of a segmented control use 4px; bridge bars use 2 to 3px. Borders are always 1px (hairline for containers, control stroke for inputs and secondary buttons); dashed borders mark empty placeholders and bridge connectors. The safety floor is drawn as a red dashed line (8 3) in charts and as a red hatched block in the bridge.

## Components

### Buttons
Restrained and exact; color does the work, not decoration.
- **Shape:** gently squared (6px), sizes 32 / 40 / 44px high with 12 / 16 / 20px side padding, 14px medium label (16px at the large size).
- **Primary:** teal with white text; hover deepens to teal-deep; press scales to 0.97.
- **Money:** the primary look without the press scale, for any action that moves or commits money (confirm terms, execute). Only color changes.
- **Secondary:** white surface, 1px control-stroke border, ink text; hover shifts to canvas.
- **Quiet:** ink-2 text with no ground; hover reveals rail gray and ink text.
- **Danger:** breach red with white text.
- **Busy:** a spinning notch icon precedes the label; disabled uses the control-stroke ground or 60% opacity.

### Chips
- **Status badge:** pill, wash ground with its state hue as text, a bold 14px icon and a 13px medium label. Tones: positive, warning, danger, neutral (rail / ink-2), accent (teal wash / teal).
- **Suggestion chip (copilot):** pill, 32px tall, canvas ground, hairline border, ink-2 text; hover darkens border and text.
- **Redaction chip:** marks personal data removed from a statement at import (ADR-028). An inline pill on rail gray with ink-2 text, a bold 12px eye-slash icon and a 12px medium label that says what was hidden ("Name hidden"). It sits in the line of text it replaces, never wraps and carries no state color.

### Cards / Containers
- **Corner Style:** 6px; the receipt alone uses 10px.
- **Background:** work surface on the cool canvas.
- **Shadow Strategy:** none (see Elevation & Depth).
- **Border:** 1px hairline.
- **Internal Padding:** 24px for working objects; 16px for compact blocks.
- **Notice:** a 6px block on the state wash with a 20px bold icon, a semibold title and ink-2 detail; danger notices are announced as alerts.

### Inputs / Fields
- **Style:** 40px tall, white, 1px control-stroke border, 6px radius, 12px side padding, ink-3 placeholder.
- **Focus:** border turns teal plus a 2px teal ring at 25% opacity.
- **Error:** border turns breach red; the error text is linked by `aria-describedby`.

### Navigation
- **Style:** rail items 40px tall at `lg`, icon (18px) plus 14px label, light text on the rail; hover lifts to a 60% ground.
- **Active:** a 10% light surface, 1px hairline ring, medium label, the icon filled and in rail-accent.
- **Mobile (below `lg`):** a fixed bottom bar of five slots: Overview, Commitments, the Copilot raised in the middle as the one teal control, Plan, and More. More opens a sheet that unfolds upward with the remaining screens (Purchase check, Statements, Audit trail) and Sign out. The profile lives in the header. The bar respects the safe area; the active tab shows a 2px teal line, a filled icon and its label. The app opens on the Copilot the first time on a phone. Motion is 150 to 240ms and off under reduced motion.
- **Persona switcher:** a segmented control on a canvas track; the selected persona is a white segment with a hairline ring.

### Liquidity Bridge (signature)
Today's balance stepping down, payday cycle by payday cycle, to the lowest point before payday, then minus the safety floor, to what is protected. The figure column shows the protected amount at hero size with its ISO code above; the chart column carries one "Amounts in CLP" unit label.
- **sm and up:** a waterfall, one column per step, totals in ink, negative cash-flow steps in context gray, positive steps in green, the floor as a red hatched block with a red border, the protected total in green (red with a prohibit icon when it is a shortfall). Dashed connectors hold the running level between columns; a control-stroke line marks zero.
- **Below sm:** one row per step on a shared horizontal zero axis, so every step stays in view and negative values cross zero legibly.
- **Motion:** bars fade and rise 6px in sequence (300ms, 60ms stagger) on entry, skipped under reduced motion. The same subtraction ledger is the pattern to reuse wherever a balance is reduced to what is free.

### Proposal Receipt (second moment)
One receipt changes state from Proposal to Confirmed to Executed; terms are read-only rows over hairlines, introduced by a lock icon.
- **Pending:** white, 10px corners, hairline border, flat.
- **Confirmed / Executed:** the border strengthens to 20% ink and the object shadow appears; a 44px round seal medallion (ink, or green once executed) stamps in with a 200ms scale from 0.85.
- **Stepper:** three 4px bars; done is ink with a check, current is teal and semibold, upcoming is hairline.
- **Validity:** a tabular countdown in ink-2, amber near expiry, red when expired.
- **Actions:** full-width money buttons at the large size; execution is always a separate step after confirmation.

### Verdict Banner
A refusal is its own component: breach-red wash, 40% red border, a prohibit icon, a red heading naming the reason, requested amount struck through in red beside the authorized amount, "nothing changed" stated plainly, and the reason code in mono.

### Money with Provenance
Every engine amount can open a popover (10px, object shadow) listing derivation, snapshot id and params version (the ids in mono). The trigger shows a dotted underline on hover or focus.

### Charts
Line charts in ink (focus, solid 2.5px with dots) and context gray (dashed 5 4), a named red floor line (dashed 8 3), hairline horizontal gridlines only, direct labels on wide screens and a legend with line samples, a crosshair tooltip, and a collapsible "Show the numbers" table.

### Copilot conversation
User messages are ink bubbles with white text (6px, tail corner 2px at bottom right). Copilot replies are canvas bubbles with a hairline border (tail corner at top left), followed by state badges (verified, clarify, read only) and the tools called in mono.

## Do's and Don'ts

### Do:
- **Do** reserve teal (#3346C8) for action, focus, selection and the current step.
- **Do** draw the data that matters in ink and its context in gray, distinguished by line style as well as tone.
- **Do** pair every green, amber or red with an icon and words.
- **Do** show the ISO code on every amount (`CLP 1,500,000`) with a real minus sign; drop it only where a header carries it once.
- **Do** keep compact `k` / `M` notation to chart axes, one unit per axis.
- **Do** set every number with tabular figures; set hashes, ids and codes in Geist Mono.
- **Do** use 6px corners for controls and containers; keep 10px for the signed receipt and overlays.
- **Do** mark selection with a white surface and a 1px hairline ring.
- **Do** route all motion through `shouldAnimate()` (`web/src/lib/motion.ts`) and respect `prefers-reduced-motion`; motion conveys state only.
- **Do** keep strings in `web/src/i18n/en.ts`, English first.

### Don't:
- **Don't** use teal as a chart series, a decorative fill or a heading color.
- **Don't** lift any surface with a shadow except the confirmed receipt and floating overlays.
- **Don't** compose three equal KPI tiles or a chat that looks like it decides.
- **Don't** animate money counting up, timer digits, block alerts or success celebrations.
- **Don't** apply a press scale to buttons that move or commit money.
- **Don't** set money in mono or show a bare currency symbol.
- **Don't** use emojis anywhere in the interface.
- **Don't** nest cards inside cards; separate sections with space and hairlines.

## Open decisions (not shipped)

- **Purchase segment in the simulator bridge.** The bridge is meant to be reused in the simulator with a purchase segment; this needs a backend contract field and is not built. The simulator currently shows a before/after impact chart.
- **Copilot prose formatting.** Currency and date formatting inside copilot prose is produced by the backend, so it may not follow the ISO Code Rule until the backend adopts it.
- **Geist and the "overused-font" detector warning.** Reviewed and kept: Geist is the pinned face.
