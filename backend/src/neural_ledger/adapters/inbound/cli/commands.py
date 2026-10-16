"""Command-line adapter: run the demo arc offline, export evidence, import bank statements, read the ledger. Standard library only."""

from __future__ import annotations

import argparse
import json
import random
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

from ....application.facade import ApplicationServices
from ....application.use_cases.actions import ActorContext
from ....domain.audit.events import Actor
from ....domain.shared.serialization import to_primitive

DEMO_SCRIPT = (
    "Will I be OK in December?",
    "Can I buy a CLP 400k laptop in 12 cuotas?",
    "Just make it work.",
    "What's actually available for me?",
    "Help me save for my trip.",
)


def run_demo(services: ApplicationServices, session_id: str = "demo") -> int:
    user = services.default_user
    print(f"Neural Ledger demo  |  user={user}  mode={services.mode}  llm={services.language_model}\n")
    proposal = None
    for message in DEMO_SCRIPT:
        reply = services.chat.handle(session_id, user, message)
        print(f"USER  > {message}\nAGENT > {reply.text}\n        [intent={reply.intent} gate={reply.gate} tools={','.join(reply.tools_called) or '-'} verified={reply.verification.ok if reply.verification else '-'}]\n")
        proposal = reply.pending_proposal or proposal
    if proposal is None:
        print("No proposal was produced; stopping.")
        return 1
    ctx = ActorContext(session_id, user, Actor.USER)
    confirmed = services.actions.confirm(ctx, proposal.proposal_id, to_primitive(proposal.terms))
    print(f"UI    > user confirms {proposal.terms.amount:,} {proposal.terms.currency} monthly -> {confirmed.status}\n")
    attack = services.chat.handle(session_id, user, "Make it 700k and execute it now.")
    print(f"USER  > Make it 700k and execute it now.\nAGENT > {attack.text}\n")
    executed = services.actions.execute(ctx, confirmed.authorization.authorization_id)
    print(f"UI    > user executes the confirmed rule -> {executed.status}\n")
    check = services.audit.verify()
    print(f"Audit chain: {'OK' if check.ok else 'BROKEN'} ({check.checked} events)")
    return 0 if check.ok else 1


def export_audit(services: ApplicationServices, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    events = services.audit.raw()
    with out.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_record(), ensure_ascii=False) + "\n")
    check = services.audit.verify()
    print(f"Wrote {len(events)} events to {out} (chain {'OK' if check.ok else 'BROKEN'})")
    return 0


def import_statement(services: ApplicationServices, path: Path, user_id: str, as_json: bool) -> int:
    try:
        content = path.read_bytes()
    except OSError as exc:
        print(f"cannot read {path}: {exc.strerror}")
        return 2
    result = services.statements.import_statement(user_id, content)
    if as_json:
        print(json.dumps(to_primitive(result), ensure_ascii=False, indent=2))
        return 0 if result.ok else 2
    if not result.ok:
        print(f"{result.status.value}: {result.message}")
        return 2
    for imported in result.data.imports:
        s = imported.statement
        state = "VERIFIED" if s.verified else "UNVERIFIED"
        print(f"{s.bank}  {s.account_type} {s.account_ref}  {s.period_start} → {s.period_end}  ({s.source}){'  PROVISIONAL' if s.provisional else ''}")
        print(f"{s.line_count} movements · charges {s.total_debits:,} · credits {s.total_credits:,} {s.currency}")
        print(f"statement_id {s.statement_id}  {state}{'  (already imported)' if imported.duplicate else ''}")
        for issue in s.issues:
            print(f"  - {issue.code} {issue.on or ''} {issue.message} (expected {issue.expected}, found {issue.found})")
        o = s.obligations
        if o is not None:
            amounts = ", ".join(f"{label} {value:,}" for label, value in (("due", o.amount_due), ("minimum", o.minimum_due)) if value is not None)
            print(f"obligations: {amounts or 'nothing printed'} {s.currency}{f' by {o.due_date}' if o.due_date else ''}")
            if o.installments:
                print(f"  cuotas still to bill {o.installments_remaining:,} {s.currency}: " + ", ".join(f"{u.month} {u.amount:,}" for u in o.upcoming))
        redaction = imported.redaction
        if redaction:
            hidden = ", ".join(f"{count} {code}" for code, count in redaction.counts.items()) or "nothing found"
            print(f"personal data hidden: {hidden} (rules {redaction.rules}, detector {redaction.detector})")
        ledger = imported.ledger
        if ledger.classifier:
            print(f"ledger: {ledger.posted} transactions ({ledger.new} new) · {ledger.uncategorized} charges uncategorized · {ledger.classifier}")
    for warning in result.warnings:
        if warning.code == "NOT_POSTED":
            print(f"ledger: {warning.message}")
        elif warning.code == "REDACTION_DEGRADED":
            print(f"personal data: {warning.message}")
    return 0


def list_transactions(services: ApplicationServices, user_id: str, as_json: bool) -> int:
    result = services.ledger.list_transactions(user_id)
    if as_json:
        print(json.dumps(to_primitive(result), ensure_ascii=False, indent=2))
        return 0
    data = result.data
    for t in data.transactions:
        confidence = f"{t.confidence:.2f}" if t.confidence is not None else "  - "
        print(f"{t.date}  {t.amount:>12,}  {t.category:<14} {confidence}  {t.merchant['untrusted_text']}")
    for t in data.spending:
        print(f"spent {t.spent:>12,} {t.currency}  {t.category:<14} ({t.count})")
    for t in data.income:
        print(f"income {t.spent:>11,} {t.currency}  ({t.count})")
    if not data.transactions:
        print("no transactions yet: import a statement (use NL_PERSISTENCE=sqlite to keep them between runs)")
    return 0


def list_statements(services: ApplicationServices, user_id: str) -> int:
    for s in services.statements.list_statements(user_id).data:
        state = ("PROVISIONAL " if s.provisional else "") + ("VERIFIED" if s.verified else "UNVERIFIED")
        print(f"{s.statement_id}  {s.bank}  {s.currency}  {s.period_start} → {s.period_end}  {s.line_count} movements  {state}")
    return 0


# ---- synthetic data: random cartolas to upload, or imported straight into the database -------------------


class SampleFile(Protocol):
    name: str
    content: bytes
    description: str


class StatementSamples(Protocol):
    """Random bank exports that add up (the generator lives in an outbound adapter; bootstrap passes it in)."""

    def checking(self, seed: int, last_month: date, months: int = 1, opening: int | None = None, salary: int | None = None) -> Sequence[SampleFile]: ...

    def card(self, seed: int, start: date, end: date) -> SampleFile: ...


class DatabaseReset(Protocol):
    """The local SQLite database, emptied in place (the adapter lives in the outbound layer; bootstrap passes it in)."""

    path: str

    def counts(self) -> Mapping[str, int]: ...

    def reset(self) -> Mapping[str, int]: ...


def _today(services: ApplicationServices) -> date:
    return services.clock.now().date() if services.clock else date.today()


def _month(text: str | None, default: date) -> date:
    if text is None:
        return default
    try:
        return date.fromisoformat(f"{text}-01")
    except ValueError as exc:
        raise SystemExit(f"--month must look like 2026-09, got {text!r}") from exc


def _seed(value: int | None) -> int:
    seed = value if value is not None else random.SystemRandom().randrange(1, 100_000)
    print(f"seed {seed}  (pass --seed {seed} to get the same files again)")
    return seed


def write_cartolas(services: ApplicationServices, samples: StatementSamples, args: argparse.Namespace) -> int:
    today = _today(services)
    seed = _seed(args.seed)
    if args.kind == "card":
        end = today if args.month is None else _month(args.month, today).replace(day=28)
        files: Sequence[SampleFile] = [samples.card(seed, end.replace(day=1), end)]
    else:
        last_full = today.replace(day=1) - timedelta(days=1)
        files = samples.checking(seed, _month(args.month, last_full), args.months, args.opening, args.salary)
    args.out.mkdir(parents=True, exist_ok=True)
    for f in files:
        path = args.out / f.name
        path.write_bytes(f.content)
        print(f"wrote {path}  ({f.description})")
    print("Upload them on the Statements page, or: neural-ledger import-statement <file>")
    return 0


def seed_database(services: ApplicationServices, samples: StatementSamples, args: argparse.Namespace) -> int:
    if services.persistence != "sqlite":
        print("seed writes to the database, but NL_PERSISTENCE is 'memory': everything would be gone when this command exits.")
        print("Run it with NL_PERSISTENCE=sqlite (make seed does), against the same NL_SQLITE_PATH as the API.")
        return 2
    user_id = args.user or services.default_user
    today = _today(services)
    seed = _seed(args.seed)
    files = list(samples.checking(seed, today.replace(day=1) - timedelta(days=1), args.months, args.opening, args.salary))
    if not args.no_card:
        files.append(samples.card(seed, today.replace(day=1), today))
    new = 0
    for f in files:
        # The real import path: read, redact, reconcile, store, post to the ledger and audit, like an upload.
        result = services.statements.import_statement(user_id, f.content)
        if not result.ok:
            print(f"{f.name}: {result.status.value}: {result.message}")
            return 2
        for imported in result.data.imports:
            s = imported.statement
            state = "already there" if imported.duplicate else ("verified" if s.verified else "UNVERIFIED")
            posted = f", {imported.ledger.posted} posted to the ledger" if imported.ledger.posted else ", stored only (unbilled)" if s.provisional else ""
            print(f"{f.description}  [{state}{posted}]")
            new += 0 if imported.duplicate else 1
    print(f"user {user_id}: {new} new statement(s). Open the app as {user_id} to see them on the Statements page.")
    return 0


def reset_database(services: ApplicationServices, database: DatabaseReset, args: argparse.Namespace) -> int:
    if services.persistence != "sqlite":
        print("reset empties the SQLite database, but NL_PERSISTENCE is 'memory': there is nothing stored to reset.")
        print("Run it with NL_PERSISTENCE=sqlite (make reset does), against the same NL_SQLITE_PATH as the API.")
        return 2
    present = {table: rows for table, rows in database.counts().items() if rows}
    total = sum(present.values())
    print(f"database {database.path}")
    for table, rows in present.items():
        print(f"  {table:<28} {rows:>8,} rows")
    if not total:
        print("already empty: nothing to delete.")
        return 0
    print(f"  {'total':<28} {total:>8,} rows")
    if not args.yes:
        try:
            answer = input(f"Delete all {total:,} rows from {database.path}? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("aborted: nothing was deleted.")
            return 1
    deleted = database.reset()
    print(f"deleted {sum(deleted.values()):,} rows from {sum(1 for rows in deleted.values() if rows)} table(s); the schema and the file are kept.")
    print("Restart the API: chat history, profiles and snapshots live in its memory. Then `make seed` to load synthetic data again.")
    return 0


def main(
    services: ApplicationServices,
    argv: list[str] | None = None,
    samples: StatementSamples | None = None,
    database: DatabaseReset | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="neural-ledger")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="run the demo arc offline")
    export = sub.add_parser("demo-and-export", help="run the demo and export the audit log as JSONL evidence")
    export.add_argument("--out", type=Path, default=Path("../evidence/sandbox-logs/audit.jsonl"))
    imp = sub.add_parser("import-statement", help="read a bank statement (Excel .xlsx, PDF or image), reconcile it and store it")
    imp.add_argument("file", type=Path)
    imp.add_argument("--user", default=None, help="owner of the statement (default: NL_PERSONA)")
    imp.add_argument("--json", action="store_true", help="print the full envelope")
    lst = sub.add_parser("statements", help="list stored statements (use NL_PERSISTENCE=sqlite to keep them between runs)")
    lst.add_argument("--user", default=None)
    txn = sub.add_parser("transactions", help="list the categorized transaction ledger built from imported statements")
    txn.add_argument("--user", default=None)
    txn.add_argument("--json", action="store_true", help="print the full envelope")
    if samples is not None:
        cart = sub.add_parser("cartola", help="write random synthetic cartolas (.xlsx) to upload in the app; touches no database")
        cart.add_argument("--kind", choices=("checking", "card"), default="checking", help="Santander checking account (default) or BICE card export")
        cart.add_argument("--month", default=None, help="YYYY-MM; checking: the last month (default: last full month), card: the export's month (default: this month to today)")
        cart.add_argument("--months", type=int, default=1, help="checking only: consecutive months, each opening at the previous closing balance")
        cart.add_argument("--seed", type=int, default=None, help="same seed, same files (default: random, printed)")
        cart.add_argument("--opening", type=int, default=None, help="checking only: opening balance of the first month, CLP (default: one salary)")
        cart.add_argument("--salary", type=int, default=None, help="checking only: monthly salary, CLP (default: random)")
        cart.add_argument("--out", type=Path, default=Path("."), help="folder for the files (default: current folder)")
        seed = sub.add_parser("seed", help="import random synthetic cartolas into the database, so the app opens with data")
        seed.add_argument("--user", default=None, help="whose data (default: NL_PERSONA); the web app's users are camila and diego")
        seed.add_argument("--months", type=int, default=6, help="months of checking-account history, ending with last month")
        seed.add_argument("--seed", type=int, default=None, help="same seed, same data: seeding twice with it adds nothing")
        seed.add_argument("--opening", type=int, default=None, help="opening balance of the first month, CLP (default: one salary)")
        seed.add_argument("--salary", type=int, default=None, help="monthly salary, CLP (default: random)")
        seed.add_argument("--no-card", action="store_true", help="skip the credit card export for the current month")
    if database is not None:
        reset = sub.add_parser(
            "reset",
            help="developer command: empty the local SQLite database in place (not the user-facing deletion of personal data, gap G03)",
        )
        reset.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args(argv)
    if args.command == "reset":
        return reset_database(services, database, args)
    if args.command == "cartola":
        return write_cartolas(services, samples, args)
    if args.command == "seed":
        return seed_database(services, samples, args)
    if args.command == "demo":
        return run_demo(services)
    if args.command == "import-statement":
        return import_statement(services, args.file, args.user or services.default_user, args.json)
    if args.command == "statements":
        return list_statements(services, args.user or services.default_user)
    if args.command == "transactions":
        return list_transactions(services, args.user or services.default_user, args.json)
    code = run_demo(services)
    return code or export_audit(services, args.out)
