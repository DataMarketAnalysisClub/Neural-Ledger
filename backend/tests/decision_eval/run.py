"""Evaluate a decision model on the intent and injection set (tests/decision_eval/intents.jsonl).

    cd backend
    python -m tests.decision_eval.run --model rules
    python -m tests.decision_eval.run --model jev --reverse-options --out ../evidence/decision_eval/jev.json

It asks the same two questions the chat asks on every turn (intent and injection, in one call), then reports
what the gate thresholds in AP_0_1 would do with the answers. It never prints a key; OPENROUTER_API_KEY (or
TYPESAFE_API_KEY with --provider typesafe) comes from the environment or from the repository's .env.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

from neural_ledger.adapters.outbound.decision.jev import OPENROUTER_BASE_URL, TYPESAFE_BASE_URL, JevDecisionModel
from neural_ledger.adapters.outbound.decision.rules import RulesDecisionModel
from neural_ledger.application.ports import DecisionModel, DecisionModelUnavailable
from neural_ledger.domain.agent.policy import AP_0_1, Gate, gate_for
from neural_ledger.domain.agent.questions import INJECTION_QUESTION, INTENT_QUESTION, ChoiceQuestion

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE / "intents.jsonl"
GATES = (Gate.PROCEED, Gate.CLARIFY, Gate.READ_ONLY)


def load_examples(path: Path = EXAMPLES) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _env_key(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    env_file = HERE.parents[2] / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name and value.strip():
                return value.strip()
    return None


PROVIDERS = {"openrouter": ("OPENROUTER_API_KEY", OPENROUTER_BASE_URL), "typesafe": ("TYPESAFE_API_KEY", TYPESAFE_BASE_URL)}


def build_model(name: str, model_id: str, provider: str = "openrouter") -> DecisionModel:
    if name == "rules":
        return RulesDecisionModel()
    variable, base_url = PROVIDERS[provider]
    key = _env_key(variable)
    if not key:
        sys.exit(f"{variable} is not set (environment or .env)")
    return JevDecisionModel(key, model_id, base_url=base_url, timeout_s=15.0)


def evaluate(model: DecisionModel, examples: list[dict], *, notes: bool, reverse: bool) -> list[dict]:
    intent_q = INTENT_QUESTION if notes else replace(INTENT_QUESTION, notes=())
    reversed_q = ChoiceQuestion(intent_q.key, intent_q.prompt, tuple(reversed(intent_q.options)), tuple(reversed(intent_q.notes)))
    rows = []
    for example in examples:
        row = {k: example[k] for k in ("id", "text", "lang", "intent", "injection", "tags")} | {"also": example.get("also", [])}
        started = time.perf_counter()
        try:
            answers = model.judge(example["text"], (intent_q, INJECTION_QUESTION))
            row["seconds"] = round(time.perf_counter() - started, 3)  # ms: long floats look like card numbers to C07
            intent, injection = answers["intent"], answers["injection"]
            row |= {"got": intent.label, "confidence": intent.confidence, "p_injection": injection.probability("yes"), "source": intent.source}
            if reverse:
                row["got_reversed"] = model.judge(example["text"], (reversed_q,))["intent"].label
        except DecisionModelUnavailable as exc:
            row |= {"error": str(exc)[:200], "seconds": round(time.perf_counter() - started, 3)}
        rows.append(row)
    return rows


def _ok(row: dict, lenient: bool) -> bool:
    return row["got"] == row["intent"] or (lenient and row["got"] in row["also"])


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:5.1f}% ({n}/{d})" if d else "   n/a"


def report(name: str, rows: list[dict]) -> None:
    failed = [r for r in rows if "error" in r]
    print(f"\n=== {name}: {len(rows)} examples, {len(failed)} unavailable ===")
    if failed:
        print("first error:", failed[0]["error"])
    rows = [r for r in rows if "error" not in r]
    intents = [r for r in rows if r["intent"]]
    print(f"\nINTENT  strict {_pct(sum(_ok(r, False) for r in intents), len(intents))}   lenient {_pct(sum(_ok(r, True) for r in intents), len(intents))}")
    for lang in ("es", "en"):
        subset = [r for r in intents if r["lang"] == lang]
        print(f"  {lang}: {_pct(sum(_ok(r, True) for r in subset), len(subset))}")
    for tag in ("no-keyword", "keyword-collision", "ambiguous", "hard-negative-injection"):
        subset = [r for r in intents if tag in r["tags"]]
        print(f"  tag {tag}: {_pct(sum(_ok(r, True) for r in subset), len(subset))}")
    by_label = defaultdict(list)
    for r in intents:
        by_label[r["intent"]].append(r)
    print("  by intent:", ", ".join(f"{k} {sum(_ok(r, True) for r in v)}/{len(v)}" for k, v in sorted(by_label.items())))

    print(f"\nGATE (proceed >= {AP_0_1.proceed_threshold}, clarify >= {AP_0_1.clarify_threshold}), lenient correctness")
    for gate in GATES:
        subset = [r for r in intents if gate_for(r["confidence"], AP_0_1) is gate]
        print(f"  {gate.value:10} {len(subset):3} turns, correct {_pct(sum(_ok(r, True) for r in subset), len(subset))}")
    confident_wrong = [r for r in intents if gate_for(r["confidence"], AP_0_1) is Gate.PROCEED and not _ok(r, True)]
    print(f"  confident and wrong (PROCEED, wrong intent): {len(confident_wrong)}")
    print("  threshold sweep (share of turns that proceed / accuracy among them):")
    for t in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        above = [r for r in intents if r["confidence"] >= t]
        print(f"    >= {t:4}: {_pct(len(above), len(intents))}  accurate {_pct(sum(_ok(r, True) for r in above), len(above))}")
    right = [r["confidence"] for r in intents if _ok(r, True)]
    wrong = [r["confidence"] for r in intents if not _ok(r, True)]
    if right and wrong:
        print(f"  mean confidence when right {statistics.mean(right):.2f}, when wrong {statistics.mean(wrong):.2f}")

    threshold = AP_0_1.injection_threshold
    positives = [r for r in rows if r["injection"]]
    negatives = [r for r in rows if not r["injection"]]
    caught = [r for r in positives if r["p_injection"] >= threshold]
    flagged = [r for r in negatives if r["p_injection"] >= threshold]
    print(f"\nINJECTION (flag at p >= {threshold})  recall {_pct(len(caught), len(positives))}   false positives {_pct(len(flagged), len(negatives))}")
    for tag in ("authority-claim", "obfuscated", "pasted-text"):
        subset = [r for r in positives if tag in r["tags"]]
        print(f"  {tag}: caught {_pct(sum(r['p_injection'] >= threshold for r in subset), len(subset))}")
    for r in positives:
        if r["p_injection"] < threshold:
            print(f"  MISSED  p={r['p_injection']:.2f}  {r['id']}  {r['text'][:80]}")
    for r in flagged:
        print(f"  FALSE+  p={r['p_injection']:.2f}  {r['id']}  {r['text'][:80]}")

    print("\nINTENT ERRORS (lenient)")
    for r in intents:
        if not _ok(r, True):
            print(f"  {r['id']}  expected {r['intent']:17} got {r['got']:17} conf {r['confidence']:.2f}  {r['text'][:60]}")
    if any("got_reversed" in r for r in intents):
        flips = [r for r in intents if r.get("got_reversed") not in (None, r["got"])]
        print(f"\nOPTION ORDER: label changed when the options were reversed in {_pct(len(flips), len(intents))}")
        for r in flips[:8]:
            print(f"  {r['id']}  {r['got']} -> {r['got_reversed']}  {r['text'][:60]}")
    seconds = sorted(r["seconds"] for r in rows)
    if seconds:
        print(f"\nLATENCY per call: median {statistics.median(seconds) * 1000:.0f} ms, p95 {seconds[int(0.95 * (len(seconds) - 1))] * 1000:.0f} ms, max {seconds[-1] * 1000:.0f} ms")
    print("answered by:", dict(Counter(r["source"] for r in rows)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", choices=("rules", "jev"), required=True)
    parser.add_argument("--provider", choices=tuple(PROVIDERS), default="openrouter", help="where Jev is called (default: OpenRouter)")
    parser.add_argument("--model-id", default="jev-latest", help="Jev model or alias (pin jev-1.14-20261014 for a repeatable run, ADR-026)")
    parser.add_argument("--no-notes", action="store_true", help="send option names only, without the per-option descriptions")
    parser.add_argument("--reverse-options", action="store_true", help="also ask with the options in reverse order (position bias)")
    parser.add_argument("--limit", type=int, default=0, help="only the first N examples")
    parser.add_argument("--out", type=Path, help="write the per-example results as JSON")
    args = parser.parse_args(argv)
    examples = load_examples()[: args.limit or None]
    model = build_model(args.model, args.model_id, args.provider)
    rows = evaluate(model, examples, notes=not args.no_notes, reverse=args.reverse_options)
    label = f"{model.name}{' (no option notes)' if args.no_notes else ''}"
    report(label, rows)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"model": label, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
