"""Command-line adapter: run the demo arc offline and export evidence. Standard library only."""

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


def main(services: ApplicationServices, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="neural-ledger")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="run the demo arc offline")
    export = sub.add_parser("demo-and-export", help="run the demo and export the audit log as JSONL evidence")
    export.add_argument("--out", type=Path, default=Path("../evidence/sandbox-logs/audit.jsonl"))
    args = parser.parse_args(argv)
    if args.command == "demo":
        return run_demo(services)
    code = run_demo(services)
    return code or export_audit(services, args.out)
