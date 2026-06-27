"""Оценочный стенд нормализатора (§7 ТЗ).

Считает precision / recall / accuracy автосопоставления на размеченном
gold-наборе и пишет отчёт. Для боевой оценки нужен gold на 200–300 пар;
в репозитории лежит небольшой образец, чтобы стенд работал «из коробки».

Запуск:
    python -m eval.normalizer_eval
    python -m eval.normalizer_eval --gold mygold.csv --services myservices.json
    python -m eval.normalizer_eval --auto 0.85 --unmatched 0.65   # покрутить пороги
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path

from normalizer import MatchResult, Normalizer, ServiceRecord
from normalizer.config import NormalizerConfig
from normalizer.lexical import HAVE_RAPIDFUZZ
from normalizer.preprocess import HAVE_PYMORPHY

_HERE = Path(__file__).resolve().parent
_DEFAULT_SERVICES = _HERE / "services_sample.json"
_DEFAULT_GOLD = _HERE / "gold_sample.csv"


@dataclass(slots=True)
class Row:
    raw: str
    expected: str | None        # None → позиция должна остаться несопоставленной
    result: MatchResult


def load_services(path: Path) -> list[ServiceRecord]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        ServiceRecord(
            service_id=str(d["service_id"]),
            service_name=d["service_name"],
            synonyms=list(d.get("synonyms") or []),
            category=d.get("category"),
        )
        for d in data
    ]


def load_gold(path: Path) -> list[tuple[str, str | None]]:
    pairs: list[tuple[str, str | None]] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            raw = (row.get("raw") or "").strip()
            if not raw:
                continue
            expected = (row.get("expected_service_id") or "").strip() or None
            pairs.append((raw, expected))
    return pairs


def evaluate(norm: Normalizer, gold: list[tuple[str, str | None]]) -> dict:
    rows = [Row(raw, exp, norm.match(raw)) for raw, exp in gold]

    positives = [r for r in rows if r.expected is not None]   # должны сопоставиться
    negatives = [r for r in rows if r.expected is None]       # должны остаться NULL

    auto = [r for r in rows if r.result.service_id is not None and not r.result.needs_review]
    auto_correct = [r for r in auto if r.expected == r.result.service_id]
    review = [r for r in rows if r.result.needs_review]

    # precision: из автосопоставлений — сколько верных
    precision = len(auto_correct) / len(auto) if auto else 0.0
    # recall: из позиций, у которых есть эталон — сколько автоматически и верно
    recall = len(auto_correct) / len(positives) if positives else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    # accuracy: доля верных решений по всем строкам
    correct_decisions = 0
    for r in rows:
        if r.expected is None:
            if r.result.service_id is None:
                correct_decisions += 1
        else:
            if r.result.service_id == r.expected and not r.result.needs_review:
                correct_decisions += 1
    accuracy = correct_decisions / len(rows) if rows else 0.0

    auto_rate = len(auto) / len(rows) if rows else 0.0

    return {
        "rows": rows,
        "metrics": {
            "total": len(rows),
            "positives": len(positives),
            "negatives": len(negatives),
            "auto_matched": len(auto),
            "auto_correct": len(auto_correct),
            "review_band": len(review),
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "accuracy": round(accuracy, 3),
            "auto_match_rate": round(auto_rate, 3),
        },
    }


def _print_report(report: dict, cfg: NormalizerConfig) -> None:
    m = report["metrics"]
    print("=" * 60)
    print("Оценка нормализатора MedArchive")
    print("=" * 60)
    print(f"Активные ступени: fuzzy={'rapidfuzz' if HAVE_RAPIDFUZZ else 'difflib-fallback'}, "
          f"лемматизация={'pymorphy3' if HAVE_PYMORPHY else 'fallback-стеммер'}")
    print(f"Пороги: auto={cfg.auto_threshold}  unmatched={cfg.unmatched_threshold}")
    print("-" * 60)
    print(f"Всего пар:            {m['total']}")
    print(f"  с эталоном:         {m['positives']}")
    print(f"  без (должны NULL):  {m['negatives']}")
    print(f"Автосопоставлено:     {m['auto_matched']}  (верных {m['auto_correct']})")
    print(f"На ручную проверку:   {m['review_band']}")
    print("-" * 60)
    print(f"Precision:            {m['precision']}")
    print(f"Recall:               {m['recall']}")
    print(f"F1:                   {m['f1']}")
    print(f"Accuracy:             {m['accuracy']}")
    print(f"Доля автосопоставл.:  {m['auto_match_rate']}  (цель ТЗ ≥ 0.70)")
    print("-" * 60)
    print("Ошибки и спорные:")
    any_bad = False
    for r in report["rows"]:
        ok = (r.expected == r.result.service_id and not r.result.needs_review) \
            if r.expected is not None else (r.result.service_id is None)
        if ok:
            continue
        any_bad = True
        conf = r.result.confidence
        flag = "review" if r.result.needs_review else "MISS"
        print(f"  [{flag}] {r.raw!r}: ожид={r.expected} получ={r.result.service_id} "
              f"({r.result.stage}, conf={conf})")
    if not any_bad:
        print("  нет — все решения верны")
    print("=" * 60)


def main() -> None:
    ap = argparse.ArgumentParser(description="Оценочный стенд нормализатора")
    ap.add_argument("--services", type=Path, default=_DEFAULT_SERVICES)
    ap.add_argument("--gold", type=Path, default=_DEFAULT_GOLD)
    ap.add_argument("--report", type=Path, default=_HERE / "report.json")
    ap.add_argument("--auto", type=float, default=None, help="auto_threshold")
    ap.add_argument("--unmatched", type=float, default=None, help="unmatched_threshold")
    args = ap.parse_args()

    cfg = NormalizerConfig()
    if args.auto is not None:
        cfg.auto_threshold = args.auto
    if args.unmatched is not None:
        cfg.unmatched_threshold = args.unmatched
    cfg.validate()

    norm = Normalizer(load_services(args.services), cfg)
    report = evaluate(norm, load_gold(args.gold))
    _print_report(report, cfg)

    args.report.write_text(
        json.dumps(report["metrics"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Отчёт: {args.report}")


if __name__ == "__main__":
    main()
