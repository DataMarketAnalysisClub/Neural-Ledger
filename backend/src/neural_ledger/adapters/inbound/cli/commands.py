"""Command-line adapter: run the demo arc offline, export evidence, import bank statements, read the ledger. Standard library only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

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
        ledger = imported.ledger
        if ledger.classifier:
            print(f"ledger: {ledger.posted} transactions ({ledger.new} new) · {ledger.uncategorized} charges uncategorized · {ledger.classifier}")
    for warning in result.warnings:
        if warning.code == "NOT_POSTED":
            print(f"ledger: {warning.message}")
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


def main(services: ApplicationServices, argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)
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
