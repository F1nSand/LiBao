"""Small deterministic metrics for the KB retrieval golden set."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RetrievalCase:
    case_id: str
    query: str
    relevant_chunk_ids: frozenset[str]
    category: str
    expect_no_answer: bool = False


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    recall_at_5: float
    recall_at_10: float
    mrr: float
    ndcg_at_10: float
    no_answer_false_positive_rate: float


def load_retrieval_cases(path: Path) -> list[RetrievalCase]:
    """Read one validated JSON object per line from a retrieval fixture."""
    cases: list[RetrievalCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            case = RetrievalCase(
                case_id=str(row["case_id"]),
                query=str(row["query"]),
                relevant_chunk_ids=frozenset(str(item) for item in row["relevant_chunk_ids"]),
                category=str(row["category"]),
                expect_no_answer=bool(row.get("expect_no_answer", False)),
            )
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid retrieval fixture at {path}:{line_number}: {exc}") from exc
        if not case.case_id or not case.query or not case.category:
            raise ValueError(f"case_id, query, and category must be non-empty at {path}:{line_number}")
        if case.expect_no_answer and case.relevant_chunk_ids:
            raise ValueError(f"no-answer case cannot contain relevant chunks at {path}:{line_number}")
        if case.case_id in seen_ids:
            raise ValueError(f"duplicate case_id {case.case_id!r} at {path}:{line_number}")
        seen_ids.add(case.case_id)
        cases.append(case)
    return cases


def evaluate_rankings(
    cases: Sequence[RetrievalCase], rankings: Mapping[str, Sequence[str]]
) -> RetrievalMetrics:
    """Calculate macro retrieval metrics; duplicate returned IDs count once."""
    answerable = [case for case in cases if case.relevant_chunk_ids and not case.expect_no_answer]
    no_answer = [case for case in cases if case.expect_no_answer]
    recall_5: list[float] = []
    recall_10: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    for case in answerable:
        ranked = list(dict.fromkeys(str(item) for item in rankings.get(case.case_id, ())))
        relevant = case.relevant_chunk_ids
        recall_5.append(len(set(ranked[:5]) & relevant) / len(relevant))
        recall_10.append(len(set(ranked[:10]) & relevant) / len(relevant))
        first_rank = next((rank for rank, chunk_id in enumerate(ranked, 1) if chunk_id in relevant), None)
        reciprocal_ranks.append(1 / first_rank if first_rank else 0.0)
        dcg = sum(1 / math.log2(rank + 1) for rank, chunk_id in enumerate(ranked[:10], 1) if chunk_id in relevant)
        ideal_count = min(len(relevant), 10)
        ideal_dcg = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
        ndcgs.append(dcg / ideal_dcg if ideal_dcg else 0.0)

    false_positives = sum(bool(rankings.get(case.case_id)) for case in no_answer)
    return RetrievalMetrics(
        recall_at_5=_mean(recall_5),
        recall_at_10=_mean(recall_10),
        mrr=_mean(reciprocal_ranks),
        ndcg_at_10=_mean(ndcgs),
        no_answer_false_positive_rate=false_positives / len(no_answer) if no_answer else 0.0,
    )


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
