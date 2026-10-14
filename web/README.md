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
| `npm test` | Vitest: formatting, API error mapping, the confirmation receipt, an axe accessibility check |
| `npm run build` | Production bundle in `dist/` |

## Rules

- **The UI never computes money.** It renders `data` and `facts` from the API. `src/lib/format.ts` only formats.
- **Every amount shows its ISO currency code** (`CLP 1,500,000`), whatever the currency.
- The **confirmation receipt** sends exactly the `terms` object it received to `POST /v1/actions/proposals/{proposal_id}/confirm`. Execution is a separate step that sends only the `authorization_id`. Nothing on screen changes until the API answers.
- Untrusted text (`{"untrusted_text": …}`, model replies) is rendered as plain text, never as HTML.
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

The existing demo stays the default. When `/health` reports `auth: "accounts"`, the UI asks for a same-origin cookie session, guards all financial routes, and removes `X-User-Id` from account requests. Account queries are keyed by `user_id`; the cache and active queries are cleared at signin, signup, demo-session, signout and sample-data changes. Camila and Diego can be explored through read-only demo sessions. A new account starts empty and shows no inherited balances, plan or advice.

For a local UI walkthrough without an accounts backend, start the development server with `VITE_ACCOUNTS_MOCK=true npm run dev`. This selects an in-memory **development-only** mock transport: use synthetic `.invalid` email addresses and disposable passwords only. The mock resets on reload, is not secure authentication, and never supplies financial projections. Its `OK` envelopes carry request-time `as_of` and `mock:accounts:` snapshot ids, which are synthetic markers, not forecast hashes or backend audit provenance. The mock's sample-data action changes its visible source status and serves a synthetic conservative capacity for the Profile illustration, not production financial data. The real backend must supply financial figures. The sample control is one-way because only `POST /v1/profile/sample-data` is specified; there is no remove-sample endpoint.

The PR1 schemas define wrapped `display_name`, nullable `declared_tolerance` / `questionnaire_version`, and `pq-0.1` question/option ids and copy keys. The UI sends `{version, answers: [{question_id, option_id}]}` and displays the server-derived profile and permitted-profile results. The mock alone reproduces the five-question score and the `tight_month` cap; the UI never calculates tolerance or money.

The PR3 HTTP handshake and generated account contracts are still pending. This preparation expects `/health.auth` (`demo` or `accounts`), `GET /v1/me` returning `{user_id, data_source: "empty" | "sample"}`, cookie-setting `POST /v1/auth/signup` with `{email, password, display_name}`, `POST /v1/auth/signin` with `{email, password}`, `POST /v1/auth/demo-session` with `{persona}`, and `POST /v1/auth/signout` with no body. Auth mutation responses are not consumed; each success is followed by `GET /v1/me`. Profile reads expect the PR1 envelope at `GET /v1/profile` and `GET /v1/profile/questionnaire`; writes use `PUT /v1/profile` with `{display_name, language}`, `POST /v1/profile/questionnaire` with the PR1 submission, and `POST /v1/profile/sample-data` with no body. The auth request/response schemas, `/health.auth`, `/v1/me` shape, signup response and cookie behavior, and sample-data toggle request body/response remain unconfirmed until the backend PR3/PR4 contract handshake; this mock does not define them. Align these draft HTTP shapes against those contracts before integration. Do not generate `src/contracts/` until #15 is merged.
