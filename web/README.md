# Web (Role D)

React + Vite + TypeScript + Tailwind v4, Radix primitives, Recharts, TanStack Query, Phosphor icons, Geist (self-hosted). Closes decision D-04 (ADR-025 in `docs/DECISIONS.md`); the design system is recorded in `docs/DESIGN.md`.

## Run

The UI follows whatever identity mode the API reports in `GET /health` (`auth`).

**Demo mode (the local default).** `NL_AUTH=demo` is the backend default and the recorded demo arc: no sign-in, the persona switch picks Camila or Diego through the `X-User-Id` header.

```bash
make api                 # backend on :8000 (offline, no keys, NL_AUTH=demo)
cd web && npm install
npm run dev              # UI on http://localhost:3000, proxies /api to :8000
```

**Accounts mode, local.** Start the same API with accounts explicitly; the dev server and its `/api` proxy stay the same, and the browser keeps the `nl_session` cookie for `localhost:3000`.

```bash
NL_AUTH=accounts make api   # sign-up, sign-in and demo personas; X-User-Id is rejected
cd web && npm run dev
```

`NL_APP_ORIGINS` (default `http://localhost:3000,http://localhost:5173`) must list the UI's origin for writes, `NL_COOKIE_SECURE=auto` sets `Secure` only over https, and `NL_DEMO_PERSONAS=true` (default) offers the Camila and Diego demo sessions on the sign-in screen. See `.env.example` and `docs/ARCHITECTURE.md`.

**Docker compose (accounts and cookie Web, paired).** `docker compose up --build` runs the API with `NL_AUTH=accounts` fixed in `docker-compose.yml` on :8000 and the built UI on :3000; nginx proxies `/api` on the same origin, so the session cookie never needs CORS.

| Script | Does |
|---|---|
| `npm run contracts` | Regenerates `src/contracts/` from `../contracts` (commit the result; CI checks it is current) |
| `npm run lint` / `npm run typecheck` | ESLint and TypeScript |
| `npm test` | Vitest: formatting, API error mapping, the confirmation receipt, redaction chips, accounts sessions and profile, axe accessibility checks |
| `npm run e2e` | Playwright against a running stack; the accounts specs skip unless `/health` reports `auth: "accounts"` |
| `npm run build` | Production bundle in `dist/` |

## Rules

- **The UI never computes money.** It renders `data` and `facts` from the API. `src/lib/format.ts` only formats.
- **Every amount shows its ISO currency code** (`CLP 1,500,000`), whatever the currency.
- The **confirmation receipt** sends exactly the `terms` object it received to `POST /v1/actions/proposals/{proposal_id}/confirm`. Execution is a separate step that sends only the `authorization_id`. Nothing on screen changes until the API answers.
- Untrusted text (`{"untrusted_text": …}`, model replies) is rendered as plain text, never as HTML.
- **Personal data stays hidden.** Statement and transaction text carries placeholder codes (`[PERSON]`, `[ID]`, …) where personal data was removed at import (ADR-028). Render it with `<RedactedText>` (`src/components/redaction.tsx`): each code becomes a chip labelled from `redaction.<CODE>` in `src/i18n/en.ts`. Never show the raw codes; the backend never translates them.
- **Generated contracts are authoritative.** `src/contracts/` is generated from `../contracts` by `npm run contracts` and never edited by hand. `src/api/accounts.ts` aliases those types and narrows them only where a schema says more than its generated type (`field` required on an `INVALID_INPUT` auth error; a profile update with at least one field).
- **English first.** Every string lives in `src/i18n/en.ts`; a new language is another file with the same shape, registered in `src/i18n/index.ts`.
- No emojis anywhere.

## Screens (demo arc)

| Route | Scene | Endpoints |
|---|---|---|
| `/` Overview | 1, 4 | `/v1/state`, `/v1/forecast`, `/v1/protected-surplus`, `/v1/savings-plan` |
| `/commitments` | 1 | `/v1/commitments`, `/v1/capacity` |
| `/simulator` Purchase check | 2, 3 | `POST /v1/simulate-purchase` |
| `/plan` Savings plan | 4 | `/v1/capacity`, `/v1/profile`, `/v1/permitted-profile`, `/v1/savings-plan` |
| `/copilot` | 5, 6 | `/v1/chat`, `/v1/actions/*` |
| `/audit` Audit trail | 6 | `/v1/audit`, `/v1/audit/verify` |
| `/statements` | — | hidden by the current statements feature flag; no upload or list UI is implemented, and enabling the flag does not add one |
| `/signin`, `/signup` | accounts | `/v1/auth/signin`, `/v1/auth/signup`, `/v1/auth/demo-session` |
| `/onboarding` | accounts | `GET` and `POST /v1/profile/questionnaire` |
| `/profile` | accounts | `/v1/me`, `GET` and `PUT /v1/profile`, `/v1/permitted-profile` (demo personas only), `/v1/auth/signout` |

## Known API gaps (for contract PRs)

- The chat reply cannot tell "offline narration" from "the verifier replaced the model's text" (`fallback_used` covers both).
- Audit events carry mismatch amounts only inside `detail`.

## Accounts mode

When `/health` reports `auth: "accounts"`, the UI asks for a same-origin cookie session, guards every financial route, and sends account requests without `X-User-Id`. Session authority is the server's HttpOnly `nl_session` cookie, never a JS-visible token or `localStorage` value. Account queries are keyed by `user_id`; the cache and active queries are cleared at signup, signin, demo-session and signout, and a late `/v1/me` answer from an older session transition cannot restore a previous identity.

- **New accounts stay empty.** `GET /v1/me` reports `data_source: "empty"`; the financial screens show an empty state, and Profile shows no capacity or permitted profile and inherits no persona's balances, projections or advice. Signup, the questionnaire and display-name edits work on an empty account.
- **Demo personas are read only.** Camila and Diego open `persona` sessions from the sign-in screen; their profiles cannot be edited (`PROFILE_READ_ONLY`), and their capacity and permitted profile come from `/v1/permitted-profile`, never from a client label.
- **The plan reads each account's stored tolerance** (`GET /v1/profile`, the PR1b change). PR1b ships inside this Web PR, not as a separate PR; its branch is kept, not deleted.
- **No sample data.** The sample-data follow-up (PR4) is cut: there is no sample-data endpoint, and the UI has no sample control and sends no such request. `sample` stays a reserved `data_source` value in `contracts/auth/me.schema.json`; the UI treats any non-persona account as empty.

Bodies follow the generated contracts. Signup (201), signin (200) and demo-session (200) return only `{user_id, expires_at}`; signout returns 204 with no body; `GET /v1/me` returns only `{user_id, data_source, expires_at}`, and the display name and server-derived tolerance come from the `GET /v1/profile` envelope. Errors come in two shapes:

- **Auth error** (`contracts/auth/error.schema.json`): `{status, message, field?}`, with `field` required on `INVALID_INPUT`, for authentication, identity, origin and read-only failures and for a request body the HTTP layer rejects (for example an empty `PUT /v1/profile`, `field: "body"`).
- **Envelope** (`contracts/common/envelope.schema.json`): `INVALID_INPUT` (HTTP 422) when the domain rejects a value, such as a display name outside its rule or a questionnaire answer for another version; `INSUFFICIENT_DATA` (HTTP 409) when an account has no financial data.

### Development mock

`VITE_ACCOUNTS_MOCK=true npm run dev` replaces the API with an in-memory, **development-only** transport for UI walkthroughs without a backend. It accepts only synthetic `.invalid` email addresses, resets on reload, sets no cookie and is not authentication: it proves nothing about cookie security, which only the real accounts backend provides. It never supplies financial figures: financial reads answer `INSUFFICIENT_DATA`, demo personas get a fixed conservative capacity for the Profile illustration only, and any route it does not serve answers 404. Its `OK` envelopes carry request-time `as_of` and `mock:accounts:` snapshot ids, which are synthetic markers, not forecast hashes or audit provenance. It mirrors the two error shapes above and scores the five `pq-0.1` questions only to stand in for the server; the UI never calculates tolerance or money.
