# Incident response: security incidents and personal data breaches

What to do when something goes wrong with an instance of Neural Ledger: detect, contain, assess, notify, recover, learn. A checklist is at the end. The privacy policy ([../PRIVACY.md](../PRIVACY.md)) says what data the system holds and who receives it; this runbook assumes you have read it.

**Norms** (as stated in [../SECURITY.md](../SECURITY.md)). The compliance map ties breach response to Ley 21.719 art. 14 sexies (`C10`, `G12`); the law is in force from 2026-12-01. Ley 21.663's incident duties (an early alert within 3 hours to the national CSIRT) bind essential services and operators of vital importance. The app is neither, and this runbook follows the same steps anyway. This is engineering guidance for counsel to review, not legal advice.

**Roles.** Fill in before running an instance with real users:

| Role | Who | Does |
|---|---|---|
| Incident lead | `[name, contact]` | Opens the incident, decides, keeps the record |
| Technical lead | `[name, contact]` | Contains, preserves evidence, recovers |
| Counsel contact | `[name, contact]` | Decides on notices to the authority and to affected people |

**Keep the incident record and every evidence copy outside the repository.** The repository is public, and a database copy can hold personal data. Never put them in `evidence/`.

## What counts as an incident

- A key or the signing secret leaked: `NL_HMAC_SECRET`, `OPENROUTER_API_KEY`, `TYPESAFE_API_KEY`, `ANTHROPIC_API_KEY` or `AZURE_LANGUAGE_API_KEY` in a commit, a log, a screenshot or a chat.
- Someone reached the SQLite file or the `ledger-data` volume without authorization, or read another user's data through the API. There is no authentication (`G01`), so check the access log too.
- The audit chain is broken: `/v1/audit/verify` answers `"ok": false`.
- Personal data found stored despite redaction: a name, RUT, account or card number, email or phone in a statement, a transaction, the audit trail or a log.
- A provider we send data to (OpenRouter, TypeSafe, Anthropic, Microsoft) reports a breach that may cover what we sent.
- A forged, altered or replayed authorization, or a savings rule the user did not confirm.

When unsure, open an incident. Closing one costs little.

## 1. Detect

- **Audit chain:** `curl http://localhost:8000/v1/audit/verify`. A healthy chain answers `{"ok": true, "checked": <n>, "broken_at": null, "reason": null}`. A broken one names the first bad sequence number and why: `sequence gap`, `prev_hash does not link` or `event content changed`.
- **Health:** `curl http://localhost:8000/health`. Check `audit_chain_ok`, and note `mode`, `language_model`, `decision_chain`, `classifier` and `pii_detector`: they tell you which providers were receiving data.
- **Audit events worth a look:** `ACTION_BLOCKED` with `blocked_reason` `AUTHORIZATION_TAMPERED`, `AUTHORIZATION_REPLAYED`, `AUTHORIZATION_NOT_FOUND`, `NEW_BENEFICIARY` or `UNKNOWN_DESTINATION`; `INJECTION_FLAGGED`; `STATEMENT_IMPORTED` with `degraded=yes`. `GET /v1/audit` returns only the events of the user named in `X-User-Id` (up to 1,000 with `?limit=`). For the whole trail, export it from a copy of the database (step 2).
- **Access log:** `docker compose logs --timestamps api` (one line per request: client address, request line, status).
- **Regression checks** on the deployed commit: `make test-security`. S01–S16 cover the attacks, `test_s15_…` personal data in every surface, `test_c10_…` the audit trail, `test_c07_…` secrets in the repository.

**Do not run `neural-ledger demo-and-export` (or `make evidence`) against the incident database.** It runs the demo arc first, as the default user, and appends its chat, confirmation and execution events before exporting. There is no export-only command; use the commands in step 2 on a copy.

Alert the incident lead as soon as one of the signs above shows. Write down the time you noticed it.

## 2. Contain

Do these in order. Preserve before you clean anything.

1. **Stop the API.** Docker: `docker compose stop api`. Locally: stop the `make api` process. Do not run `docker compose down`: `--volumes` deletes the database, and removing the container deletes its log.
2. **Preserve evidence** in a folder outside the repository, e.g. `INCIDENT_DIR=~/incidents/<yyyy-mm-dd>-<short-name>`:

   ```bash
   mkdir -p "$INCIDENT_DIR"
   docker compose logs --no-color --timestamps api > "$INCIDENT_DIR/api.log"
   docker volume ls --filter name=ledger-data          # e.g. neural-ledger_ledger-data
   docker run --rm -v <volume>:/data:ro -v "$INCIDENT_DIR":/out alpine tar -czf /out/ledger-data.tgz -C /data .
   # locally instead: cp backend/var/neural_ledger.db* "$INCIDENT_DIR"/   (or the file at NL_SQLITE_PATH)
   sha256sum "$INCIDENT_DIR"/* > "$INCIDENT_DIR/SHA256SUMS"
   ```

   Then extract or copy it again into a working folder (`tar -xzf ledger-data.tgz -C <work dir>`) and use only that: opening a database writes to it, so never open the preserved one. From `backend/`, with `<copy>` the working copy's `neural_ledger.db`:

   ```bash
   # verify the chain
   PYTHONPATH=src python3 -c "import sys; from neural_ledger.adapters.outbound.persistence.sqlite import SqliteDatabase, SqliteAuditLog; from neural_ledger.domain.audit.events import verify_chain; print(verify_chain(SqliteAuditLog(SqliteDatabase(sys.argv[1])).events()))" <copy>
   # export the whole trail as JSONL
   PYTHONPATH=src python3 -c "import json, sys; from neural_ledger.adapters.outbound.persistence.sqlite import SqliteDatabase, SqliteAuditLog; [print(json.dumps(e.to_record(), ensure_ascii=False)) for e in SqliteAuditLog(SqliteDatabase(sys.argv[1])).events()]" <copy> > "$INCIDENT_DIR/audit.jsonl"
   ```

3. **Rotate the signing secret** if it may have leaked, or if an authorization looks forged: generate a new one (`python -c "import secrets; print(secrets.token_hex(32))"`) and set `NL_HMAC_SECRET` in `.env`. Every authorization is checked against the current secret when it is executed, so the ones signed with the old secret are blocked as `AUTHORIZATION_TAMPERED`. Expect those events after a rotation. Authorizations expire after 10 minutes anyway; savings rules already executed stay. Users confirm again.
4. **Rotate provider keys** that may have leaked: revoke and regenerate `OPENROUTER_API_KEY`, `TYPESAFE_API_KEY`, `ANTHROPIC_API_KEY` or `AZURE_LANGUAGE_API_KEY` in the provider's console, and put the new value in `.env`. A key that reached a commit is leaked even after the commit is removed: rotate it.
5. **Switch to offline mode** if a provider is involved or you are unsure: in `.env` set `NL_LLM=scripted`, `NL_DECISION_CHAIN=rules`, `NL_CLASSIFIER=naive_bayes` and `NL_PII_DETECTOR=none` (an empty value means the same). After a restart, `/health` must show `"mode": "offline"` and `"pii_detector": "none"`. Offline mode accepts the development secret; set a real one anyway.

Keep the API stopped until step 5 (Recover) unless the incident lead decides otherwise. After editing `.env`, start it with `docker compose up -d api` (it recreates the container with the new settings).

## 3. Assess

Answer these and write the answers in the incident record.

- **What happened and when.** The first bad event in the trail (`broken_at`, or the first suspicious event), the access log, and the time it was noticed.
- **Which users.** Statements, transactions, proposals, authorizations and audit events all carry a `user_id`. List the ones affected.
- **Which data.** After redaction (ADR-028), the database holds financial data: amounts, dates, merchants, categories and masked accounts. It can still hold personal data: a name outside a transfer line that the rules missed, statements stored before `st-0.2` (raw text), and client addresses in the access log. Chat history is in memory only, so a copy of the database does not include it. When unsure, treat the data as personal.
- **Did it leave to a provider.** Which settings were on at the time (`/health`, `.env`, the deploy history). In the trail, `STATEMENT_IMPORTED` events record `detector=` and `classifier=`, and `DECISION` events record which model answered (`jev:…` or `rules-…`). What each provider receives is in the privacy policy's "Who receives data".
- **Risk to people.** Could the data identify someone, or show their finances? How likely is misuse? Which incidents need a notice is to confirm with counsel; record the facts they need to decide.

## 4. Notify

- **Ley 21.719 art. 14 sexies.** Prepare a notice for the authority and one for the affected people. Whether this incident must be reported, which authority receives it, how fast and in what form, and when the affected people must be told, are to confirm with counsel. Do not wait for counsel to write the facts down.
- **What a notice says:** what happened and when, which data and how many people, what was done to contain it, what people can do (for example, watch for messages that quote their transactions), and a contact (`[contact email]`).
- **Ley 21.663.** Its early alert (within 3 hours to the national CSIRT) binds essential services and operators of vital importance; the app is neither. Follow the same pace anyway: tell the incident lead and counsel within 3 hours of noticing.
- **Providers.** If a key leaked, tell the provider when you rotate it. If the incident started at a provider, follow its notice and record what it says.

## 5. Recover

1. **Fix the cause** first: a code change through the normal review, a rotated secret, or a setting.
2. **Choose the data to restart from.**
   - If the preserved copy's chain verifies and the data was not altered, restore it into a fresh volume: `docker compose down --volumes`, `docker compose create` (makes an empty volume), `docker run --rm -v <volume>:/data -v "$INCIDENT_DIR":/in alpine tar -xzf /in/ledger-data.tgz -C /data`, then `docker compose up -d`. Locally, copy the files back to `NL_SQLITE_PATH`.
   - Otherwise start empty: `docker compose down --volumes`, `docker compose up --build -d`, then re-seed synthetic data (`docker compose exec api neural-ledger seed --user camila`, see [SYNTHETIC_DATA.md](SYNTHETIC_DATA.md)). Real users import their statements again.
   - Never edit or re-seal audit events to make a broken chain pass. That would hide the tampering. Keep the broken copy as evidence and start a new database.
3. **Run `make test-all`** (it includes the security suite) on the commit you will deploy. It must pass.
4. **Check before reopening:** `/v1/audit/verify` answers `"ok": true`, `/health` shows `audit_chain_ok: true` and the intended `mode`, `classifier` and `pii_detector`.

## 6. Learn

- **Record the incident:** timeline, data and users affected, notices sent and when, the fix and its commit. Keep it with the evidence, outside the repository. A summary without personal data can go into "Known risks" in [../SECURITY.md](../SECURITY.md).
- **Add a regression test** in `backend/tests/security` that reproduces the attack. Assume the model is hostile (fakes in `backend/tests/security/helpers.py`). A new control gets a `C` row in the compliance map; a duty that cannot be built yet gets a `G` row and a strict xfail.
- **Review [../PRIVACY.md](../PRIVACY.md)** if what is stored, or who receives it, changed.

## Checklist

- [ ] Incident opened; time noticed and incident lead recorded
- [ ] API stopped (`docker compose stop api`); volume and container kept
- [ ] Access log, database and hashes saved outside the repository
- [ ] Chain verified and trail exported from a working copy, not the preserved one
- [ ] `NL_HMAC_SECRET` rotated, if it may have leaked or an authorization looks forged
- [ ] Provider keys rotated, if they may have leaked
- [ ] Offline mode on, if a provider is involved or in doubt; `/health` checked
- [ ] Users, data and providers involved written down
- [ ] Incident lead and counsel told within 3 hours; notices to the authority and to people decided with counsel
- [ ] Cause fixed; data restored or started empty; no audit event edited
- [ ] `make test-all` passes; `/v1/audit/verify` ok; `/health` as intended
- [ ] Incident recorded; regression test added in `backend/tests/security`; PRIVACY.md reviewed
