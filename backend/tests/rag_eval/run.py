"""Evaluate a knowledge base on the question set (tests/rag_eval/questions.jsonl), ADR-039.

    cd backend
    PYTHONPATH=src:. python -m tests.rag_eval.run --kb lexical
    PYTHONPATH=src:. python -m tests.rag_eval.run --kb chroma            # needs the `rag` extra; downloads the model once
    PYTHONPATH=src:. python -m tests.rag_eval.run --kb chroma --kb-dir ../var/chroma

Each question names the card ids that answer it, or none (off-topic). Questions whose cards are not written yet
are skipped and counted. Per language and overall:

    recall@1, recall@3   an expected card is the first / among the first three passages
    mrr                  mean of 1 / rank of the first expected card (0 when it is not in the top 3)
    top_score            median best score on answerable questions, and the highest on off-topic ones

The gap between the two `top_score` numbers is where the use case's `min_score` belongs: above every off-topic
question, below most answerable ones. The report is written to evidence/rag_eval/<kb>.json.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from neural_ledger.adapters.outbound.knowledge.corpus_loader import load_cards
from neural_ledger.adapters.outbound.knowledge.lexical import LexicalKnowledgeBase
from neural_ledger.application.ports import KnowledgeBase
from neural_ledger.domain.education.concepts import ConceptCard, Passage

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "questions.jsonl"
EVIDENCE = HERE.parents[2] / "evidence" / "rag_eval"
K = 3


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build(name: str, cards: tuple[ConceptCard, ...], kb_dir: str | None = None) -> KnowledgeBase:
    if name == "lexical":
        return LexicalKnowledgeBase(cards)
    from neural_ledger.adapters.outbound.knowledge.chroma import ChromaKnowledgeBase

    return ChromaKnowledgeBase(cards, kb_dir)


def answerable(questions: list[dict], ids: set[str]) -> tuple[list[dict], int]:
    """Questions whose expected cards all exist (off-topic ones always count), and how many were skipped."""
    kept = [q for q in questions if all(i in ids for i in q["expected"])]
    return kept, len(questions) - len(kept)


def score(questions: list[dict], results: Sequence[Sequence[Passage]]) -> dict:
    def metrics(rows: list[tuple[dict, Sequence[Passage]]]) -> dict:
        ranks = []
        for q, passages in rows:
            got = [p.card.id for p in passages[:K]]
            ranks.append(next((r for r, i in enumerate(got, 1) if i in q["expected"]), None))
        n = len(ranks)
        return {
            "n": n,
            "recall@1": round(sum(1 for r in ranks if r == 1) / n, 3) if n else None,
            "recall@3": round(sum(1 for r in ranks if r is not None) / n, 3) if n else None,
            "mrr": round(sum(1 / r for r in ranks if r) / n, 3) if n else None,
        }

    pairs = list(zip(questions, results))
    on_topic = [(q, r) for q, r in pairs if q["expected"]]
    off_topic = [(q, r) for q, r in pairs if not q["expected"]]
    report = {"all": metrics(on_topic)}
    for lang in sorted({q["lang"] for q, _ in on_topic}):
        report[lang] = metrics([(q, r) for q, r in on_topic if q["lang"] == lang])
    best = [r[0].score if r else 0.0 for _, r in on_topic]
    report["top_score"] = {
        "answerable_median": round(statistics.median(best), 3) if best else None,
        "answerable_min": round(min(best), 3) if best else None,
        "off_topic_max": round(max((r[0].score if r else 0.0 for _, r in off_topic), default=0.0), 3),
    }
    report["misses"] = [
        {"q": q["q"], "lang": q["lang"], "expected": q["expected"], "got": [p.card.id for p in r[:K]]}
        for q, r in on_topic
        if not any(p.card.id in q["expected"] for p in r[:K])
    ]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kb", choices=("lexical", "chroma"), default="lexical")
    parser.add_argument("--kb-dir", default=None, help="persistent Chroma index (default: in memory)")
    parser.add_argument("--corpus", type=Path, default=None, help="another card folder (default: the package's corpus)")
    parser.add_argument("--out", type=Path, default=None, help="default: evidence/rag_eval/<kb>.json")
    args = parser.parse_args(argv)

    cards = load_cards(args.corpus)
    questions, skipped = answerable(load_questions(), {c.id for c in cards})
    kb = build(args.kb, cards, args.kb_dir)
    started = time.monotonic()
    results = [kb.search(q["q"], q["lang"], K) for q in questions]
    elapsed = time.monotonic() - started
    report = {"kb": args.kb, "knowledge_base": kb.name, "cards": len(cards), "skipped": skipped, "seconds": round(elapsed, 2)}
    report |= score(questions, results)

    for part in ("all", "es", "en"):
        m = report.get(part)
        if m:
            print(f"{part:<4} n={m['n']:<3} recall@1={m['recall@1']}  recall@3={m['recall@3']}  mrr={m['mrr']}")
    print(f"top score {report['top_score']}  skipped {skipped} (cards not written yet)  in {report['seconds']} s")
    for miss in report["misses"][:10]:
        print(f"  miss {miss['lang']} {miss['q']!r}: expected {miss['expected']}, got {miss['got']}")
    out = args.out or EVIDENCE / f"{args.kb}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
