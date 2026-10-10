# Web (Role D)

Framework is decision D-04: whatever ships fastest for the demo, web first (Angular is fine; wrap with Ionic later if needed).

## Rules
- **The UI never computes money.** It renders `data` and `facts` from the API.
- The **confirmation card** shows exactly `pending_proposal.terms` and sends those same terms to `POST /v1/actions/proposals/{proposal_id}/confirm`. Never let the user or the agent edit the terms on the card.
- Types are generated from `contracts/` (see `contracts/README.md`).
- Untrusted text (`{"untrusted_text": …}`) is rendered as plain text, never as HTML.

## Screens for the demo arc
1. Dashboard: balance, commitments by month, conservative vs. typical trough chart with the floor line (`GET /v1/forecast?scenario=…`).
2. What-if: purchase form → verdict, before/after chart, alternatives (`POST /v1/simulate-purchase`).
3. Chat (`POST /v1/chat`) with the confirmation card when `pending_proposal` is present.
4. Protected surplus and capacity (`GET /v1/protected-surplus`, `GET /v1/capacity`).
5. Audit view with blocked attempts and the chain status (`GET /v1/audit`, `GET /v1/audit/verify`).

## API
Base URL `http://localhost:8000`; select the persona with the header `X-User-Id: camila` or `diego`. `GET /health` shows the mode (offline or live).
