from tools.bakeoff import format_verdict, parse_variant


def test_parse_variant_splits_model_from_reasoning_effort():
    assert parse_variant("google/gemini-2.5-flash") == {
        "spec": "google/gemini-2.5-flash",
        "model": "google/gemini-2.5-flash",
        "reasoning": "",
    }
    assert parse_variant("google/gemini-2.5-pro@high")["reasoning"] == "high"
    # Ollama tags use a colon, so the effort separator must not be one.
    assert parse_variant("qwen2.5:7b")["model"] == "qwen2.5:7b"


def _summary(spec, passed, cost, score=1.0, warnings=0):
    split = {"cases": 4, "passed": passed, "pass_rate": passed / 4, "score": score,
             "recall_hits": 0, "recall_total": 0, "recall": None, "violations": 0,
             "warnings": warnings, "unstable": 0}
    return {"spec": spec, "usage": {"cost_usd": cost},
            "splits": {"all": split, "tune": split, "holdout": split}}


def test_format_verdict_calls_out_paying_more_for_nothing():
    verdict = format_verdict([_summary("cheap", 3, 0.01, score=0.90),
                              _summary("pricey", 3, 0.10, score=0.90)])
    assert "not worth it" in verdict
    assert "10.0x the cost" in verdict

    better = format_verdict([_summary("cheap", 2, 0.01, score=0.70),
                             _summary("pricey", 4, 0.05, score=0.95)])
    assert "score +0.25" in better


def test_format_verdict_still_ranks_when_every_case_passes():
    """A saturated gate must not report every model as equal — that hides the answer"""
    verdict = format_verdict([_summary("cheap", 4, 0.01, score=0.80, warnings=40),
                              _summary("pricey", 4, 0.08, score=0.95, warnings=10)])

    assert "score +0.15" in verdict
    assert "pass columns say nothing here" in verdict
