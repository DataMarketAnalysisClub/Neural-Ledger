# Web (Role D)

React + Vite + TypeScript + Tailwind v4, Radix primitives, Recharts, TanStack Query, Phosphor icons, Geist (self-hosted). Closes decision D-04 (ADR-025 in `docs/DECISIONS.md`); the design system is recorded in `docs/DESIGN.md`.

## Run

```bash
make api                 # backend on :8000 (offline, no keys)
cd web && npm install
npm run dev              # UI on http://localhost:3000, proxies /api to :8000
```

Or `docker compose up --build`: API on :8000, UI on :3000 (nginx proxies `/api`).

| Script | Does |
|---|---|
| `npm run contracts` | Regenerates `src/contracts/` from `../contracts` (commit the result; CI checks it is current) |
| `npm run lint` / `npm run typecheck` | ESLint and TypeScript |
| `npm test` | Vitest: formatting, API error mapping, the confirmation receipt, redaction chips, axe accessibility checks |
| `npm run build` | Production bundle in `dist/` |

## Rules

- **The UI never computes money.** It renders `data` and `facts` from the API. `src/lib/format.ts` only formats.
- **Every amount shows its ISO currency code** (`CLP 1,500,000`), whatever the currency.
- The **confirmation receipt** sends exactly the `terms` object it received to `POST /v1/actions/proposals/{proposal_id}/confirm`. Execution is a separate step that sends only the `authorization_id`. Nothing on screen changes until the API answers.
- Untrusted text (`{"untrusted_text": …}`, model replies) is rendered as plain text, never as HTML.
- **Personal data stays hidden.** Statement and transaction text carries placeholder codes (`[PERSON]`, `[ID]`, …) where personal data was removed at import (ADR-028). Render it with `<RedactedText>` (`src/components/redaction.tsx`): each code becomes a chip labelled from `redaction.<CODE>` in `src/i18n/en.ts`. Never show the raw codes; the backend never translates them.
- **English first.** Every string lives in `src/i18n/en.ts`; a new language is another file with the same shape, registered in `src/i18n/index.ts`.
- No emojis anywhere.

## Screens (demo arc)

| Route | Scene | Endpoints |
|---|---|---|
| `/` Overview | 1, 4 | `/v1/state`, `/v1/forecast`, `/v1/protected-surplus`, `/v1/savings-plan` |
| `/commitments` | 1 | `/v1/commitments`, `/v1/capacity` |
| `/simulator` Purchase check | 2, 3 | `POST /v1/simulate-purchase` |
| `/plan` Savings plan | 4 | `/v1/capacity`, `/v1/permitted-profile`, `/v1/savings-plan` |
| `/copilot` | 5, 6 | `/v1/chat`, `/v1/actions/*` ("New conversation" starts a new `session_id`; the log is not stored yet) |
| `/audit` Audit trail | 6 | `/v1/audit` (all or this conversation), `/v1/audit/verify` |
| `/profile` | — | `/v1/profile`, `/v1/profile/questionnaire` (read only) |
| `/statements` | — | `/v1/statements`, `/v1/statements/{id}`, `POST /v1/statements`, `/v1/transactions` (imports feed the ledger only; projections still use the demo scenario, ADR-029) |

## Known API gaps (for contract PRs)

- The chat reply cannot tell "offline narration" from "the verifier replaced the model's text" (`fallback_used` covers both).
- The profile is read only (`/profile`): `PATCH /v1/profile` and `POST /v1/profile/questionnaire` are not wired yet, and the questionnaire wording (`questionnaire.*` copy keys) is not written yet.
- No chat history endpoint: a reload or "New conversation" drops the log (`GET /v1/chat/history` is planned).
- Audit events carry mismatch amounts only inside `detail`.
