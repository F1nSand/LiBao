import math
from pathlib import Path

from app.evaluation.kb_retrieval import RetrievalCase, evaluate_rankings, load_retrieval_cases


def test_perfect_rankings_and_empty_no_answer_have_perfect_metrics():
    cases = [
        RetrievalCase("q1", "query one", frozenset({"a", "b"}), "zh_phrase"),
        RetrievalCase("q2", "query two", frozenset(), "no_answer", expect_no_answer=True),
    ]

    metrics = evaluate_rankings(cases, {"q1": ["a", "b"], "q2": []})

    assert metrics.recall_at_5 == 1.0
    assert metrics.recall_at_10 == 1.0
    assert metrics.mrr == 1.0
    assert metrics.ndcg_at_10 == 1.0
    assert metrics.no_answer_false_positive_rate == 0.0


def test_metrics_use_reciprocal_rank_macro_recall_and_binary_ndcg():
    case = RetrievalCase("q1", "query", frozenset({"a", "b"}), "zh_phrase")

    metrics = evaluate_rankings([case], {"q1": ["wrong", "b"]})

    assert metrics.recall_at_5 == 0.5
    assert metrics.recall_at_10 == 0.5
    assert metrics.mrr == 0.5
    assert math.isclose(metrics.ndcg_at_10, (1 / math.log2(3)) / (1 + 1 / math.log2(3)))


def test_duplicate_hits_do_not_inflate_recall_or_shift_relevant_rank():
    case = RetrievalCase("q1", "query", frozenset({"a", "b"}), "mixed_language")

    metrics = evaluate_rankings([case], {"q1": ["a", "a", "b"]})

    assert metrics.recall_at_5 == 1.0
    assert metrics.mrr == 1.0


def test_no_answer_false_positive_rate_counts_nonempty_results():
    cases = [
        RetrievalCase("q1", "query", frozenset(), "no_answer", expect_no_answer=True),
        RetrievalCase("q2", "query", frozenset({"a"}), "identifier"),
    ]

    metrics = evaluate_rankings(cases, {"q1": ["irrelevant"], "q2": ["a"]})

    assert metrics.no_answer_false_positive_rate == 1.0


def test_answer_recall_metrics_are_zero_for_a_no_answer_only_suite():
    case = RetrievalCase("q1", "query", frozenset(), "no_answer", expect_no_answer=True)

    metrics = evaluate_rankings([case], {"q1": []})

    assert metrics.recall_at_5 == 0.0
    assert metrics.recall_at_10 == 0.0
    assert metrics.mrr == 0.0
    assert metrics.ndcg_at_10 == 0.0


def test_golden_fixture_loads_stable_case_ids_and_categories():
    fixture = Path(__file__).parent / "fixtures" / "kb_retrieval_golden.jsonl"

    cases = load_retrieval_cases(fixture)

    assert len(cases) == 8
    assert {case.case_id for case in cases} >= {"zh_phrase", "mixed_language", "identifier", "no_answer"}
    assert next(case for case in cases if case.case_id == "no_answer").expect_no_answer
