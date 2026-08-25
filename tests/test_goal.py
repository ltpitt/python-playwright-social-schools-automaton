import sys
from unittest.mock import patch

import pytest

from socialschools.digest.prompt import PROMPT_PLACEHOLDERS, load_prompt_template, render_prompt
from tools.goal import (
    best_turn,
    build_improver_prompt,
    failing_cases,
    format_ledger_row,
    is_better,
    rank,
    repair_prompt,
    should_stop,
    stalled_turns,
    strip_fences,
    turn_record,
    validate_template,
)


def _turn(turn, holdout_passed=0, holdout_cases=4, score=0.5, rejected=None):
    summary = {
        "usage": {"cost_usd": 0.01},
        "splits": {
            "tune": {"passed": 8, "cases": 12},
            "holdout": {"passed": holdout_passed, "cases": holdout_cases},
            "all": {"score": score},
        },
    }
    return turn_record(turn, summary, f"template {turn}", f"goal_output/prompt_turn_{turn}.txt",
                       rejected=rejected)


class TestTemplateValidation:
    def test_the_shipped_template_is_valid(self):
        assert validate_template(load_prompt_template()) == []

    def test_shipped_template_renders_with_real_values(self):
        rendered = render_prompt(
            load_prompt_template(),
            language="en", title="Test Article", body="Test body.", attachments="", hints="")
        assert "Test Article" in rendered
        assert "<<" not in rendered
        # The JSON example is plain JSON now, with nothing left to escape.
        assert '{\n  "translated_title"' in rendered

    def test_rejects_a_dropped_placeholder(self):
        template = load_prompt_template().replace("<<HINTS>>", "")
        assert any("<<HINTS>>" in problem for problem in validate_template(template))

    def test_rejects_an_invented_placeholder(self):
        template = load_prompt_template() + "\n<<SCHOOL_NAME>>"
        assert any("<<SCHOOL_NAME>>" in problem for problem in validate_template(template))

    def test_a_literal_brace_is_no_longer_a_problem(self):
        """The whole point of <<NAME>>: JSON braces need no escaping."""
        assert validate_template(load_prompt_template() + '\n{"extra": [1]}') == []

    def test_rejects_a_truncated_answer(self):
        problems = validate_template("Sorry, I cannot help with that.")
        assert len(problems) == 1 and "expected at least" in problems[0]

    def test_placeholders_match_what_the_template_uses(self):
        template = load_prompt_template()
        assert all(f"<<{name}>>" in template for name in PROMPT_PLACEHOLDERS)


class TestRepairPrompt:
    def test_shows_the_problems_and_the_rejected_answer(self):
        prompt = repair_prompt("a bad template", ["dropped placeholder(s): <<BODY>>"])
        assert "dropped placeholder(s): <<BODY>>" in prompt
        assert "a bad template" in prompt
        assert "<<LANGUAGE>>" in prompt


class TestStripFences:
    def test_removes_a_fenced_block(self):
        assert strip_fences("```text\nhello\n```") == "hello"

    def test_leaves_unfenced_text_alone(self):
        assert strip_fences("  hello\nworld  ") == "hello\nworld"

    def test_leaves_an_unclosed_fence_content(self):
        assert strip_fences("```\nhello") == "hello"


class TestRanking:
    def test_more_holdout_passes_beats_a_higher_score(self):
        assert rank(_turn(1, holdout_passed=3, score=0.1)) > rank(_turn(2, holdout_passed=2, score=0.9))

    def test_score_breaks_a_tie_on_passes(self):
        assert rank(_turn(1, holdout_passed=2, score=0.7)) > rank(_turn(2, holdout_passed=2, score=0.6))

    def test_best_turn_prefers_the_earliest_of_equal_turns(self):
        history = [_turn(0, holdout_passed=2), _turn(1, holdout_passed=2)]
        assert best_turn(history)["turn"] == 0

    def test_best_turn_ignores_a_later_regression(self):
        history = [_turn(0, holdout_passed=1), _turn(1, holdout_passed=3), _turn(2, holdout_passed=0)]
        assert best_turn(history)["turn"] == 1


class TestNoiseMargin:
    """One case in twenty moves on a rerun of the same prompt, so one case proves nothing."""

    def test_a_single_holdout_case_is_not_an_improvement(self):
        assert not is_better(_turn(1, holdout_passed=3, score=0.50),
                             _turn(0, holdout_passed=2, score=0.50))

    def test_two_holdout_cases_are(self):
        assert is_better(_turn(1, holdout_passed=4, score=0.50),
                         _turn(0, holdout_passed=2, score=0.50))

    def test_a_clear_score_gain_counts_without_moving_a_case(self):
        assert is_better(_turn(1, holdout_passed=2, score=0.60),
                         _turn(0, holdout_passed=2, score=0.50))

    def test_a_score_gain_inside_the_noise_does_not(self):
        assert not is_better(_turn(1, holdout_passed=2, score=0.505),
                             _turn(0, holdout_passed=2, score=0.500))

    def test_losing_a_case_is_never_an_improvement(self):
        assert not is_better(_turn(1, holdout_passed=1, score=0.99),
                             _turn(0, holdout_passed=2, score=0.50))

    def test_best_turn_keeps_the_baseline_over_a_one_case_gain(self):
        history = [_turn(0, holdout_passed=3, score=0.50), _turn(1, holdout_passed=4, score=0.51)]
        assert best_turn(history)["turn"] == 0


class TestStalling:
    def test_a_single_baseline_has_not_stalled(self):
        assert stalled_turns([_turn(0)]) == 0

    def test_improvement_resets_the_count(self):
        history = [_turn(0, holdout_passed=1), _turn(1, holdout_passed=3)]
        assert stalled_turns(history) == 0

    def test_a_one_case_gain_still_counts_as_stalled(self):
        """Otherwise the loop spends its patience chasing noise."""
        history = [_turn(0, holdout_passed=1), _turn(1, holdout_passed=2)]
        assert stalled_turns(history) == 1

    def test_counts_consecutive_turns_without_improvement(self):
        history = [_turn(0, holdout_passed=2), _turn(1, holdout_passed=2), _turn(2, holdout_passed=1)]
        assert stalled_turns(history) == 2

    def test_a_rejected_turn_counts_as_stalled(self):
        history = [_turn(0, holdout_passed=2), _turn(1, holdout_passed=2, rejected="dropped {hints}")]
        assert stalled_turns(history) == 1


class TestShouldStop:
    def test_stops_when_every_holdout_case_passes(self):
        stop, reason = should_stop([_turn(0, holdout_passed=4, holdout_cases=4)], 5, 2)
        assert stop and "goal met" in reason

    def test_keeps_going_while_cases_still_fail(self):
        stop, _ = should_stop([_turn(0, holdout_passed=3, holdout_cases=4)], 5, 2)
        assert not stop

    def test_stops_when_the_turn_budget_is_spent(self):
        history = [_turn(n, holdout_passed=n) for n in range(4)]
        stop, reason = should_stop(history, 3, 99)
        assert stop and "budget exhausted" in reason

    def test_stops_after_patience_turns_without_improvement(self):
        history = [_turn(0, holdout_passed=2), _turn(1, holdout_passed=2), _turn(2, holdout_passed=2)]
        stop, reason = should_stop(history, 10, 2)
        assert stop and "stalled" in reason

    def test_patience_is_not_spent_by_one_bad_turn(self):
        history = [_turn(0, holdout_passed=2), _turn(1, holdout_passed=1)]
        stop, _ = should_stop(history, 10, 2)
        assert not stop

    def test_an_empty_holdout_never_counts_as_met(self):
        stop, _ = should_stop([_turn(0, holdout_passed=0, holdout_cases=0)], 5, 2)
        assert not stop


class TestLedger:
    def test_row_carries_the_numbers_and_the_note(self):
        row = format_ledger_row(_turn(2, holdout_passed=3, score=0.75, rejected="dropped {body}"))
        assert row.split("\t") == ["2", "8/12", "3/4", "0.750", "0.0100",
                                   _turn(2)["sha"], "dropped {body}"]

    def test_missing_cost_renders_as_a_dash(self):
        record = _turn(1)
        record["cost_usd"] = None
        assert "\t-\t" in format_ledger_row(record)


def _result(case_id, violations=(), missing=(), split="tune"):
    return {
        "id": case_id,
        "split": split,
        "violations": list(violations),
        "recall_missing": list(missing),
        "recall_near_misses": {},
    }


class TestFeedback:
    def test_passing_cases_are_not_fed_back(self):
        results = [_result("a"), _result("b", violations=["invented date"])]
        assert [r["id"] for r in failing_cases(results)] == ["b"]

    def test_worst_case_comes_first(self):
        results = [_result("a", missing=["towel"]), _result("b", violations=["x", "y"])]
        assert [r["id"] for r in failing_cases(results)] == ["b", "a"]

    def test_feedback_is_capped(self):
        results = [_result(f"case-{n}", violations=["x"]) for n in range(20)]
        assert len(failing_cases(results)) == 6

    def test_prompt_carries_the_template_the_reason_and_the_digest(self):
        results = [_result("post_1", violations=["invented date"], missing=["towel"])]
        product = {"cases": [{
            "id": "post_1",
            "source": {"title": "Test Article", "body": "Bring a towel."},
            "product": {"notification": "Test digest text"},
        }]}
        prompt = build_improver_prompt("CURRENT TEMPLATE {hints}", results, product)
        assert "CURRENT TEMPLATE {hints}" in prompt
        assert "invented date" in prompt
        assert "missing 'towel'" in prompt
        assert "Test digest text" in prompt
        assert "untrusted school website" in prompt

    def test_prompt_survives_a_case_with_no_digest(self):
        results = [_result("post_1", violations=["product has no digest"])]
        product = {"cases": [{"id": "post_1", "source": {"title": "T", "body": "B"}, "product": None}]}
        assert "(no digest produced)" in build_improver_prompt("T {hints}", results, product)


class TestProposal:
    def test_improver_model_override_is_temporary(self):
        from socialschools.config import get_config
        from tools.goal import propose_template

        cfg = get_config()
        before = cfg.LLM_MODEL
        seen = {}

        class FakeProvider:
            def complete(self, prompt):
                seen["model"] = get_config().LLM_MODEL
                return "new template"

        with patch("tools.goal.get_provider", return_value=FakeProvider()):
            assert propose_template("prompt", model="some/other-model") == "new template"
        assert seen["model"] == "some/other-model"
        assert cfg.LLM_MODEL == before

    def test_the_digest_schema_is_off_while_rewriting_the_prompt(self):
        """With it on, the model answers with a Digest instead of a template."""
        from socialschools.config import get_config
        from tools.goal import propose_template

        cfg = get_config()
        cfg.LLM_STRUCTURED_OUTPUT = True
        seen = {}

        class FakeProvider:
            def complete(self, prompt):
                seen["structured"] = get_config().LLM_STRUCTURED_OUTPUT
                return "new template"

        with patch("tools.goal.get_provider", return_value=FakeProvider()):
            propose_template("prompt")
        assert seen["structured"] is False
        assert cfg.LLM_STRUCTURED_OUTPUT is True

    def test_model_is_restored_even_when_the_call_fails(self):
        from socialschools.config import get_config
        from tools.goal import propose_template

        cfg = get_config()
        cfg.LLM_STRUCTURED_OUTPUT = True
        before = cfg.LLM_MODEL

        class BoomProvider:
            def complete(self, prompt):
                raise RuntimeError("backend down")

        with patch("tools.goal.get_provider", return_value=BoomProvider()):
            with pytest.raises(RuntimeError):
                propose_template("prompt", model="some/other-model")
        assert cfg.LLM_MODEL == before
        assert cfg.LLM_STRUCTURED_OUTPUT is True


def _summary(holdout_passed, holdout_cases=2, score=0.5):
    return {
        "usage": {"cost_usd": 0.02},
        "splits": {
            "tune": {"passed": 4, "cases": 6},
            "holdout": {"passed": holdout_passed, "cases": holdout_cases},
            "all": {"score": score},
        },
    }


def _valid_template(marker):
    return (f"{marker} " + "x" * 600
            + "\n{}\n<<LANGUAGE>> <<TITLE>> <<BODY>><<ATTACHMENTS>><<HINTS>>")


@pytest.fixture
def loop(tmp_path, monkeypatch):
    """goal.main() with the corpus, the model and the filesystem all faked out."""
    from tools import goal as module

    prompt_path = tmp_path / "digest_prompt.txt"
    prompt_path.write_text(_valid_template("BASELINE") + "\n", encoding="utf-8")
    monkeypatch.setattr(module, "PROMPT_PATH", str(prompt_path))
    monkeypatch.setattr(module, "ARCHIVE_DIR", str(tmp_path / "goal_output"))
    monkeypatch.setattr(module, "LEDGER", str(tmp_path / "goal_ledger.tsv"))
    monkeypatch.setattr(module, "load_prompt_template",
                        lambda path=None: prompt_path.read_text(encoding="utf-8").rstrip("\n"))

    def run(scores, proposals, turns=3, cases=2):
        """scores: holdout passes per measure() call. proposals: what the model returns."""
        measured = iter(scores)
        offered = iter(proposals)
        monkeypatch.setattr(module, "measure",
                            lambda samples=1: (_summary(next(measured), cases), [], {"cases": []}))
        monkeypatch.setattr(module, "propose_template",
                            lambda prompt, model=None: next(offered))
        monkeypatch.setattr(sys, "argv", ["goal.py", "--turns", str(turns), "--patience", "2"])
        module.main()
        return prompt_path.read_text(encoding="utf-8")

    return run


class TestLoopWiring:
    def test_stops_as_soon_as_the_goal_is_met(self, loop):
        final = loop(scores=[0, 2], proposals=[_valid_template("WINNER")])
        assert "WINNER" in final

    def test_a_regression_is_thrown_away_and_the_baseline_restored(self, loop):
        final = loop(scores=[1, 0, 0],
                     proposals=[_valid_template("WORSE"), _valid_template("ALSO_WORSE")])
        assert "BASELINE" in final

    def test_keeps_the_best_turn_not_the_last(self, loop):
        # A two-case gain, because one case is inside the rerun noise and is ignored.
        final = loop(scores=[0, 2, 0], cases=4,
                     proposals=[_valid_template("BEST"), _valid_template("WORSE")], turns=2)
        assert "BEST" in final

    def test_a_one_case_gain_does_not_win_the_prompt(self, loop):
        """It is a coin flip, and keeping it means the loop tuned toward noise."""
        final = loop(scores=[0, 1, 0], cases=4,
                     proposals=[_valid_template("LUCKY"), _valid_template("WORSE")], turns=2)
        assert "BASELINE" in final

    def test_an_invalid_candidate_never_reaches_the_prompt_file(self, loop, tmp_path):
        # Each turn costs two proposals now: the answer, then the repair attempt.
        final = loop(scores=[0], proposals=["not a template", "still not a template",
                                            "nor this one", "nor this"])
        assert "BASELINE" in final
        assert "not a template" not in final
        assert (tmp_path / "goal_output" / "rejected_turn_1.txt").exists()

    def test_the_repair_retry_rescues_a_malformed_answer(self, loop):
        final = loop(scores=[0, 2], proposals=["missing every placeholder",
                                               _valid_template("REPAIRED")])
        assert "REPAIRED" in final

    def test_the_ledger_records_every_turn(self, loop, tmp_path):
        loop(scores=[0, 2, 0], cases=4,
             proposals=[_valid_template("BEST"), _valid_template("WORSE")], turns=2)
        rows = (tmp_path / "goal_ledger.tsv").read_text(encoding="utf-8").strip().splitlines()
        assert rows[0].startswith("turn\t")
        assert [row.split("\t")[0] for row in rows[1:]] == ["0", "1", "2"]
