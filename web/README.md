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
| `/copilot` | 5, 6 | `/v1/chat`, `/v1/actions/*` |
| `/audit` Audit trail | 6 | `/v1/audit`, `/v1/audit/verify` |
| `/statements` | — | hidden until `/v1/statements` reaches main (`VITE_FEATURE_STATEMENTS=true`) |

## Known API gaps (for contract PRs)

- The chat reply cannot tell "offline narration" from "the verifier replaced the model's text" (`fallback_used` covers both).
- No HTTP endpoint for the user profile (declared tolerance); the Plan screen lets the user choose the tolerance to test.
- Audit events carry mismatch amounts only inside `detail`.

## Accounts UI preparation (not integrated)

The existing demo stays the default (including the current backend's `/health` response without `auth`). When `/health` reports `auth: "accounts"`, the UI asks for a same-origin cookie session, guards all financial routes, and removes `X-User-Id` from account requests. Account queries are keyed by `user_id`; the cache and active queries are cleared at signin, signup, demo-session, signout and sample-data changes. Late `/v1/me` answers from an older session transition cannot restore a previous identity. Camila and Diego use read-only `persona` sessions; their profile permitted/capacity values come from the permitted-profile endpoint, not the `sample` label. A new account starts `empty` and shows no inherited balances, plan or advice.

For a local UI walkthrough without an accounts backend, start the development server with `VITE_ACCOUNTS_MOCK=true npm run dev`. This selects an in-memory **development-only** mock transport: registration accepts synthetic `.invalid` email addresses and disposable passwords only. The mock resets on reload, is not secure authentication, and never supplies financial projections. Its `OK` envelopes carry request-time `as_of` and `mock:accounts:` snapshot ids, which are synthetic markers, not forecast hashes or backend audit provenance. The mock's sample-data action changes its visible source status and serves synthetic conservative capacity for the Profile illustration; demo personas have their own read-only `persona` source and use the same fixture capacity (E05/E14) only in this mock. Neither is production financial data; the real backend must supply financial figures. The sample control is one-way in the current UI mock. No sample-data toggle request/response or remove-sample API contract has been agreed yet.

The PR1 schemas define wrapped `display_name`, nullable `declared_tolerance` / `questionnaire_version`, and `pq-0.1` question/option ids and copy keys. The UI sends `{version, answers: [{question_id, option_id}]}` and displays the server-derived profile and permitted-profile results. The mock alone reproduces the five-question score and the `tight_month` cap; the UI never calculates tolerance or money.

The PR3 request/response contracts are defined at `contracts/auth/*.schema.json` and `contracts/profile/profile_update.schema.json` in the accounts HTTP worktree; this branch hand-aligns its DTOs and mock, but does **not** integrate an accounts backend. Signup (201), signin (200), and demo-session (200) respond with only `{user_id, expires_at}`; `GET /v1/me` responds with only `{user_id, data_source: "empty" | "sample" | "persona", expires_at}`. The UI fetches the PR1-wrapped profile separately for display name and server-derived tolerance. The signup request requires `{email, password, display_name}` with optional `language`; signin uses `{email, password}` and demo-session uses `{persona: "camila" | "diego"}`. `PUT /v1/profile` accepts a nonempty subset of `{display_name, language}`; questionnaire reads/submissions retain the PR1 envelope and submission contracts. Auth/profile-write errors use generic `{status, message, field?}` (with `field` required on `INVALID_INPUT`), while financial and questionnaire envelopes retain PR1 shapes. Signout returns 204 with no body. Session authority is the server's HttpOnly `nl_session` cookie, never a JS-visible token or localStorage value; this mock does not implement cookie security. `/health.auth` and the real HTTP/cookie behavior remain an integration gate, with PR2 integrity and #15 still pending human clearance. Sample-data toggle shape is intentionally undefined; do not infer a new API from the one-way mock. Do not generate `src/contracts/` until #15 is merged.
