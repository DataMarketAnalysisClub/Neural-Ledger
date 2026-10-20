# TODO

What is left, as of Oct 19, 2026, evening Chile (submission target day). Repo state on GitHub: `main` at `7012f41` (release PR #42 merged, so #33–#41 are on `main`); `staging` at `4810161`, 12 commits ahead of `main` (#43 terms and email checks, #44 receipt workflow, #45 receipts renumbered to ADR-039, #51 phone guide panel); `Documentation` 4 commits ahead of `staging` with no PR; `ops/deploy-neural-ledger` with no PR (not re-checked); no `submission-*` tag yet; 52 remote branches, 32 of them merged into `staging`. Open PRs: #52 (MCP connectors, Fintoc; CI red on backend and compose) and #54 (education RAG; CI green). The user-memory stack #46–#50 and #53 is merged only into stacked `a/*` branches, not into `staging`. The Notion rows below were last checked at 15:40 and not re-checked since. Roles are defined in `README.md`.

Deadline: Oct 20, 23:59 Beijing (about 12:59 pm Chile). Target submission: today, Oct 19.

The plan for the final stage (Oct 21 to Nov 13, seven features, four sprints) is in Notion: "Plan de desarrollo, etapa final (Shenzhen)", under the project page. See "Final stage" below for this week's part of it.

## This week (from the final-stage plan)

| Item | State | Next step |
|---|---|---|
| Promote `staging` to `main` (PR #43) and upload the submission | #43 merged into `staging` (09:26); not on `main` | **`staging` now also carries #44** (receipts, chat expenses, daily check-in; merged 15:25, after the plan was written). Decide: ship #44 in the submission, or promote only #43 (merge `d4557d2` into `main`) |
| Decide whether the `Documentation` PDFs go in the submission; if so, merge today | Open, no PR | Open the PR into `staging` (or straight into the release) |
| Tag the submitted commit `submission-2026-10-20`; freeze `main` until Oct 28 | Not tagged | Tag after the upload; new work goes to `staging` only |
| `ops/deploy-neural-ledger` into `staging` by PR; delete the 32 remote branches merged into `staging` | No PR; 52 remote branches | |
| Kick-off sync Oct 21: accept the plan, hand out ADR numbers | Not yet | **ADR numbers collide.** #46 reserves ADR-040 to ADR-047 for the user-memory plan (ADR-040 salary, ADR-047 typed memory), but #52 also uses ADR-047 (MCP connectors) and #54 uses ADR-040 (education). Proposal: education → ADR-048, connectors → ADR-049 |
| User-memory stack (#46–#50, #53: declared salary, income calendar) | Merged into stacked `a/*` branches only | Open the PR from the top of the stack into `staging` |
| #52 read-only MCP connectors and Fintoc (ADR-047) | Open, CI red (backend, compose) | Fix CI; renumber its ADR (see above) |
| #54 financial education from concept cards (ADR-040, 70 cards, Chroma in its own container) | Open, CI green, review required (Role B) | New feature after the freeze: team decision to merge; renumber its ADR (see above); open items in `docs/plans/EDUCATION_RAG.md` |

## Submission (Notion Task Board, still open)

| Task | Board owner | Due | Notion status | Repo state / next step |
|---|---|---|---|---|
| Presentation deck, 10 minutes max | Joaquín (E), visuals by Vicente (D) | Oct 19 | Sin empezar | Nothing in the repo yet. **Owner conflict:** the assignment list at the bottom of the Notion project page gives the PowerPoint to Lucho. Settle who builds it |
| Demo video first take | Vicente (D) | Oct 18 (overdue) | Sin empezar | `make seed` gives the app data to film. Project page list: Lucho, max 3 min |
| Demo video final, 5 minutes max | Vicente (D) | Oct 19 | Sin empezar | Project page list also names a second video (max 10 min, Lucho); the rules allow 5 min. Settle which videos and their length |
| Export sandbox logs and audit evidence | Baptiste (C) | Oct 19 | Sin empezar | `make evidence` exists; `evidence/sandbox-logs/`, `screenshots/` and `test-results/` still hold only `.gitkeep`. Run it on the final build. `category_eval/`, `decision_eval/` and `backtest/` are filled. Project page list: Vicho |
| README, deployment instructions, documented test cases | Baptiste (C) | Oct 19 | En curso | README has `docker compose up --build` and the modes; check it from a clean checkout and after #41 (option B, Docker secret for the data key). Project page list: Vicho |
| Full demo path from a clean checkout (feature freeze) | All | Oct 17 (overdue) | Sin empezar | #42 is merged: do it now on `main`, and again on whatever gets promoted (#43, maybe #44) |
| Bug bash and all tests green | All | Oct 18 (overdue) | En curso | CI was green on #42 (backend, web, compose) and is green on #54, which carries today's `staging`. #52 is red. Playwright e2e not re-run since the redesign (#36, #39) |
| Submit and verify the upload | All | Oct 19 | Sin empezar | Before Oct 20, 23:59 Beijing |
| Buffer day: verify the submission only | All | Oct 20 | Sin empezar | No new work |

Done today: release PR #42 merged into `main` (close its board row); #43 (disposable/mailless email domains refused at sign-up, unreviewed-Chinese warning, draft `docs/TERMS.md`) and #44 (receipt workflow) merged into `staging`; technical documentation and the security self-assessment written (LaTeX sources and built PDFs in `docs/latex/`, branch `Documentation`). **Open a PR for `Documentation`** so both reach `main` before submission.

## Overdue Notion rows (decide: do, close as covered, or drop)

| Task | Board owner | Due | Notion status | Note |
|---|---|---|---|---|
| Jev go/no-go (reliable enough for the pitch?) | Luis-Felipe (B) | Oct 14 | Sin empezar | ADR-026 still "Proposed"; the re-pin and its eval (`evidence/decision_eval/`) are merged. The deck needs this answer |
| Wireframes for the 6-scene demo arc | Vicente (D) | Oct 6 | En curso | `docs/DESIGN.md` is a design system, not a scene arc; the app is built. Close as covered or add the scenes |
| LLMFallbackDecisionModel (intent, risk signals, injection flag) | Luis-Felipe (B) | Oct 11 | Sin empezar | Not built. Past the freeze: drop it from scope and say so in the docs |
| Collect hours per person; assign roles and integration owner | All | Oct 4 | Sin empezar | Still open; also unchecked in the project page's "Decisions to lock" |
| Stretch: proactive alerts, alternative purchase options, multilingual | All | Oct 18 | En curso | Multilingual done (#37: es, zh). Alerts and alternatives not built; past the freeze |

## Listed in Notion but not on the board

From the Notion project page; none of these has a Task Board row.

| Item | Where in Notion | State |
|---|---|---|
| RACI matrix | §4 Team and roles ("to do") | Not done |
| Named integration owner | §4, §10 | Not named |
| "Decisions to lock" checklist | §10 | All seven boxes unchecked, though most are decided in practice (scope, roles, stack, savings framing, Jev policy, repo and board). Tick them or leave the page as a historical baseline |
| Tech stack table | §12 | Empty; the recommendation (Ionic + Angular, MongoDB/DynamoDB) does not match the repo (Vite + React + TypeScript, SQLite, Python). Fill it in from the repo |
| Personal data filtering for cartolas (Bato) | §15 list | Done (ADR-028) |
| OCR adapted to different cartolas (Joaquín) | §15 list | Done (ADR-031, two read pipelines) |
| Profile creation / initial profiling (Bruno) | §15 list | Built (risk questionnaire, profile editing); ADR-030 still "Proposed" |
| Security report (all) | §15 list | Done (`Documentation` branch) |
| "User Record" for the agent (David's proposal) | §1 | Not built as such; the versioned profile (ADR-030) is the nearest thing |
| Demo arc, 6 scenes | §8 | `make demo` runs it offline; golden answers E01–E14. Re-check on the redesigned UI while filming |

## Joaquín (ledger, classifier and compliance)

| Item | Status | Next step |
|---|---|---|
| Technical documentation and security self-assessment | **Written and built** (`Documentation` branch) | Open the PR; fold in anything #41 changed after the drafts |
| Presentation deck | Not started | See Submission above |
| Placeholders in `docs/PRIVACY.md` and `docs/runbooks/INCIDENT_RESPONSE.md` | Open (still on `staging` at `4810161`) | `PRIVACY.md` lines 11, 12, 65: `[team or legal entity name]`, `[contact email]` twice; `INCIDENT_RESPONSE.md` lines 11–13 (three `[name, contact]` roles) and 86 (`[contact email]`). Repo is public: use a team address |
| Financial education (PR #54, ADR-040 on the branch) | **Built**: 35 concepts × es/en, lexical search by default, Chroma opt-in in its own container (`docker compose --profile rag`); recall@3 1.0 on 52 questions | Get a Role B review; renumber the ADR; open decisions in `docs/plans/EDUCATION_RAG.md` (cap EXPLAIN at T0, Spanish scope refusal, two unsourced card claims, the lexical off-topic score 0.409 near its 0.45 floor) |
| Draft terms of use (`docs/TERMS.md`, #43) | Merged into `staging` | Review against `PRIVACY.md`; same contact placeholders |
| Receipts (final-stage feature 1, owner E) | **Partly built by #44** (Luis-Felipe): stamp, print and OCR reading, de-duplication against statements, user correction | Re-plan rows 10, 11, 20, 30 and 38 of the final-stage plan around what #44 already does. Its ADR is now **ADR-039** (#45); still needs Roles A, C and E to review it |
| Statement-based model (ADR-029 step 2) | **Merged** (#33) | Follow-ups: model cache / statement cap, overlapping statements counted twice, estimator warnings not forwarded, more own-money rules, backtest on real statements |
| Re-categorization over user labels | **Open decision** (ADR-023) | Recommendation: a user's label is never overwritten (art. 6). Nothing re-categorizes today |
| ADR-035 (Jev out of the shared `.env`) | Proposed | Every role initials it |

## Compliance and suitability gaps left (strict xfails)

| Gap | What is missing | Note |
|---|---|---|
| G01 | Authentication | Cookie accounts exist (#27, #41), but the test still exercises the `X-User-Id` path. ADR-033 step 3 |
| G02 | Export of all of a user's data | ADR-033 step 4 |
| G04 | Correction of statement lines (ADR-021) | Categories done (#32, picker #35), so the G04 xfail is gone; line correction is still open with no test |
| G05, G06 | Opposition/blocking; recorded consent before an import | #41 added a sandbox notice acknowledged at sign-up; not yet the per-purpose consent G06 tests |
| UG01–UG03 | Suitability report; refuse proposals from a superseded state; warn on an off-track near-term goal | Unassigned |
| ADR-014 (2 strict xfails, 1 non-strict) | `size_plan` not monotone | Team decision (Role A); needs a new `params_version` |

Closed: G03 deletion (#41), G07 and G11 (#29), G08–G10 and G12 (#28), G04 for categories (#32). For the self-assessment's known-risk list, these are the open items.

Not testable as code, also open: the impact assessment (Ley 21.719 art. 15 ter), safeguards for transfers abroad (art. 27), an age check (art. 16 quáter).

## Open decisions (team)

- Still "Proposed": ADR-025 (frontend stack), ADR-026 (Jev first), ADR-027 (OpenRouter only), ADR-030 (versioned profile), ADR-033 (gap-closing plan), ADR-034 (installments, needs A + E), ADR-035 (needs every role).
- Built, review pending: ADR-036 savings category (Role A), ADR-037 liquidity floor (Roles A and B), ADR-038 option B for the public demo, ADR-039 receipts (Roles A, C and E). ADR-032 is Accepted (Role E, Oct 18).
- ADR numbering: see "This week" (ADR-040 and ADR-047 are each claimed twice).
- ADR-014: `size_plan` non-monotone. ADR-029 steps 3–7 are plan. ADR-021 decided, not built.
- Still open: rename `FC_0_1` (holds fc-0.3); a 404 still carries an `INSUFFICIENT_DATA` envelope rather than `NOT_FOUND`.

## Done (for the record)

- Oct 15–16: #23 profile page and sessions; #24 synthetic cartolas and `seed`; #25 Jev categories with naive Bayes fallback. 19 Notion rows marked "Listo" on Oct 15.
- Oct 17: #26 web onboarding; #27 cookie-authenticated HTTP; #28 G08–G10, G12; #30 `make reset`.
- Oct 18: #29 G07, G11, ADR-033; #31 installments 1–48; #32 G04 categories, Jev re-pin, fc-0.3.
- Oct 19: #33 statement-based model; #35 category picker, overview guide; #36 phone layout and teal onboarding; #37 language picker (es, zh); #38 savings category (ADR-036); #39 web redesign and split sign-in; #40 liquidity floor (ADR-037); #41 option B hardening, G03 deletion (ADR-038); #42 release PR opened and merged into `main`; #43 email domain checks, Chinese warning, draft terms; #44 receipts, chat expenses and daily spending check-in (into `staging`); `ops/deploy-neural-ledger` public demo on nixbox with the data key as a Docker secret (branch, no PR). LaTeX technical documentation and security self-assessment written (`Documentation`). Notion: both documents set to "Listo"; bug bash and stretch set to "En curso"; final-stage plan page added. Evening: #45 receipts ADR renumbered to ADR-039 and #51 phone guide panel (into `staging`); #46–#50 and #53 user memory and declared salary (stacked `a/*` branches only); #52 MCP connectors opened (CI red); #54 financial education opened (CI green).

## Environment

- Run `ruff check .` before pushing (CI's first backend step).
- Playwright needs a browser: `cd web && npx playwright install chromium`, then run with `PW_CHANNEL=""` against `make api` + `npx vite --port 3000` (CI does not run e2e).
- `make api` does not read `.env`; export it first (`set -a; . ./.env; set +a`) or use `docker compose`.
- `npm run build` and `npm run typecheck` rewrite the tracked `web/tsconfig.tsbuildinfo`; restore it instead of committing it.
- Housekeeping: three stale stashes (Oct 13) and the local branches merged into `staging` (`c/*`, `features/*`, `OCR_*`) can be dropped.
- Locally the full backend suite has 175 failures that also fail on `staging`: missing `disposable-email-domains` and `email_validator`, and receipt OCR. Install them before trusting a local run.
- Work branch: `c/education-rag` (PR #54).
