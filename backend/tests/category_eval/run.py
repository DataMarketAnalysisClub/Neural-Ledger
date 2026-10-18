"""Evaluate a transaction classifier on the category set (tests/category_eval/categories.jsonl), ADR-032.

    cd backend
    PYTHONPATH=src:. python -m tests.category_eval.run --model naive_bayes
    PYTHONPATH=src:. python -m tests.category_eval.run --model jev --out ../evidence/category_eval/jev.json
    PYTHONPATH=src:. python -m tests.category_eval.run --model chain        # jev, then naive_bayes

Each line is classified as posting would, then gated by the domain (`accept`: in the vocabulary and
confidence >= 0.5). Three numbers matter, per slice (`seen`: merchants in the naive Bayes training data,
`unseen`: Chilean merchants it never saw):

    coverage        accepted / all             how many charges get a category
    precision       correct / accepted          how often an accepted category is right
    wrong_accepted  wrong and accepted / all    the cost: a charge shown in the wrong category

Lower wrong_accepted beats higher coverage: an uncategorized charge is honest, a wrong one misleads.
The texts are already in their redacted form (`[PERSON]`, `[NUMBER]`), as Jev would receive them.
OPENROUTER_API_KEY comes from the environment or the repository's .env; it is never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from neural_ledger.adapters.outbound.classifier.jev import JevTransactionClassifier
from neural_ledger.adapters.outbound.classifier.sklearn_text import SklearnTextClassifier, naive_bayes
from neural_ledger.adapters.outbound.decision.jev import OPENROUTER_BASE_URL, JevDecisionModel
from neural_ledger.application.ports import TransactionClassifier
from neural_ledger.application.services.classifier_fallback import FallbackClassifier
from neural_ledger.domain.ledger.categorization import UNCATEGORIZED, accept
from tests.decision_eval.run import _env_key

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE / "categories.jsonl"


def load_examples(path: Path = EXAMPLES) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build(name: str, model_id: str) -> TransactionClassifier:
    nb = SklearnTextClassifier(naive_bayes, method="naive_bayes")
    if name == "naive_bayes":
        return nb
    key = _env_key("OPENROUTER_API_KEY")
    if not key:
        sys.exit("OPENROUTER_API_KEY is not set (environment or .env)")
    jev = JevTransactionClassifier(JevDecisionModel(key, model_id, base_url=OPENROUTER_BASE_URL, timeout_s=20.0))
    return jev if name == "jev" else FallbackClassifier([jev, nb])


def score(examples: list[dict], guesses) -> dict:
    """Metrics overall and per slice, plus the confusions behind wrong_accepted."""

    def metrics(rows: list[tuple[dict, str]]) -> dict:
        accepted = [(e, c) for e, c in rows if c != UNCATEGORIZED]
        correct = sum(1 for e, c in accepted if c == e["category"])
        n = len(rows)
        return {
            "n": n,
            "coverage": round(len(accepted) / n, 3) if n else 0.0,
            "precision": round(correct / len(accepted), 3) if accepted else None,
            "wrong_accepted": round((len(accepted) - correct) / n, 3) if n else 0.0,
        }

    decided = [(e, accept(g)) for e, g in zip(examples, guesses)]
    report = {"all": metrics(decided)}
    for slice_ in sorted({e["slice"] for e in examples}):
        report[slice_] = metrics([(e, c) for e, c in decided if e["slice"] == slice_])
    confusions = Counter((e["category"], c) for e, c in decided if c not in (UNCATEGORIZED, e["category"]))
    report["confusions"] = [{"expected": a, "got": b, "count": n} for (a, b), n in confusions.most_common()]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", choices=("naive_bayes", "jev", "chain"), default="naive_bayes")
    parser.add_argument("--model-id", default="jev-1.13.0", help="Jev version (pinned; see ADR-026)")
    parser.add_argument("--out", type=Path, default=None, help="write the full report as JSON")
    args = parser.parse_args(argv)

    examples = load_examples()
    classifier = build(args.model, args.model_id)
    started = time.monotonic()
    guesses = classifier.classify([e["text"] for e in examples])
    elapsed = time.monotonic() - started
    report = {"model": args.model, "classifier": classifier.name, "seconds": round(elapsed, 1), **score(examples, guesses)}
    report["sources"] = dict(Counter(g.source or classifier.name for g in guesses))

    for part in ("all", "seen", "unseen"):
        m = report[part]
        print(f"{part:<7} n={m['n']:<3} coverage={m['coverage']:.3f}  precision={m['precision']}  wrong_accepted={m['wrong_accepted']:.3f}")
    print(f"classifier {report['classifier']}  answered by {report['sources']}  in {report['seconds']} s")
    for c in report["confusions"][:8]:
        print(f"  {c['expected']} -> {c['got']} ×{c['count']}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
