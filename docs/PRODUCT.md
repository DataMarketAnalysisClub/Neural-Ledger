# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React + Vite + TypeScript + Tailwind v4 + shadcn/ui (Radix) + Recharts + TanStack Query, in `web/`. Chosen by Role D (closes decision D-04 in `docs/SCOPE.md`). The backend is the existing Python API (`backend/`, FastAPI adapter) and the JSON Schemas in `contracts/`.

## Users

- **Primary:** people with installment debt (cuotas, BNPL, 分期) whose bank balance looks healthy while much of it is already committed to future payments. Synthetic personas: Camila (salaried, 1.8M CLP net, three cuotas overlapping in December) and Diego (freelance, same balances, variable income).
- **Evaluators:** FinTechathon 2026 judges (International Track, Shenzhen), who see the product mainly through a 4 to 5 minute demo video and the repository. Security is 30% of the score.

## Product Purpose

Neural Ledger is an AI cash-flow copilot. It answers, in increasing difficulty: *Can I afford this?* · *How much is really available after protecting future commitments?* · *What should I do with the surplus, and can you do it for me?* Success means the user sees that their balance is not what they can spend, makes a purchase decision with the real cost in front of them, and sets up a savings rule they explicitly confirmed.

## Positioning

Balance ≠ available ≠ protected surplus. The agent wallet has a bounded mandate: it reads (T0), analyzes (T1), executes only what the user confirmed (T2), and can never do T3 things. Models only interpret language; deterministic code computes every number and authorizes every action; only the user confirms, through the UI; every step is recorded in a hash-chained audit log anyone can verify. The innovation is not that the AI obeys: it reasons about the future and refuses when the numbers say no.

## Operating Context

- Demo arc (golden answers E01 to E14): December crunch flagged; a 400k laptop in 12 cuotas fits only the typical scenario; alternatives instead of a bypass; protected surplus and capacity; a 100k/month savings rule proposed, confirmed and executed; a 700k request blocked with the audit showing why.
- Runs offline with no keys (scripted language model + rules decision model); live mode swaps in a real LLM.
- Persona chosen by the `X-User-Id` header (sandbox identity, not real authentication).

## Capabilities and Constraints

- Sandbox only: synthetic data, no real money, accounts or personal data. The repository is public.
- The UI never computes money: it renders `data` and `facts` returned by the API.
- The confirmation card shows exactly the proposal's terms and sends those same terms back; terms are never editable.
- Merchant, ledger and statement text is untrusted data, rendered as plain text, never as HTML or instructions.
- English first; every string lives in a dictionary so more languages can be added later.
- Every amount shows its ISO currency code from the API, formatted like `CLP 1,500,000`; never a bare currency symbol.
- No emojis anywhere.
- Out of scope: real banking, investment advice, crypto, brokerage, tax optimization. The final action is a savings or buffer rule.
- Open: bank statement import (`/v1/statements`) exists only on the `staging` branch; branches are cut from `main`.

## Evidence on Hand

- Persona fixtures: `data/personas/camila.json`, `data/personas/diego.json` (synthetic; one merchant label carries a deliberate prompt-injection string).
- Golden answers and security tests: `backend/tests/golden`, `backend/tests/security` (S01 to S12).
- Figma mockup "Mockup Neural Ledger" (9 desktop + 5 mobile frames), treated as evidence of content, not as visual authority.
- No real users, testimonials, customers or benchmarks exist; none may be invented.

## Product Principles

1. Show the gap between balance and what is truly free before anything else.
2. The engine speaks in facts; the copilot interprets. Never blur the two voices.
3. Refusal is a feature: when the numbers say no, show why and what would fit instead.
4. Nothing moves without the user's explicit confirmation of exact terms, and every attempt is visible afterwards.
5. Be unambiguous for an international audience: explicit currency, plain words over local jargon.

## Accessibility & Inclusion

WCAG 2.2 AA. Color never carries meaning alone; charts have text alternatives; respect reduced motion; the demo must stay legible in a compressed video.
