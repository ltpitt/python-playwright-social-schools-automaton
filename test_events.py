import json
import logging

import pytest

from check_events import (
    config_changes,
    failures,
    flag_regressions,
    load_events,
    number_shifts,
    review,
    run_order,
    split_latest,
)
from events import Event, emit, environment, logfmt, sha8


@pytest.fixture(autouse=True)
def events_to_tmp(tmp_path, monkeypatch):
    """Keep every test's events in its own file, never the repo's."""
    import events as module

    path = tmp_path / "events.jsonl"
    monkeypatch.setattr(module, "EVENTS_PATH", str(path))
    logger = logging.getLogger("events")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    yield path
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def _written(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class TestEvent:
    def test_writes_one_line_with_the_basics(self, events_to_tmp):
        with Event("article", article_id="post_1") as event:
            event["topics"] = 2
        records = _written(events_to_tmp)
        assert len(records) == 1
        assert records[0]["event"] == "article"
        assert records[0]["article_id"] == "post_1"
        assert records[0]["topics"] == 2
        assert records[0]["outcome"] == "ok"
        assert records[0]["duration_ms"] >= 0
        assert records[0]["run_id"]

    def test_an_exception_still_produces_an_event(self, events_to_tmp):
        with pytest.raises(ValueError):
            with Event("article") as event:
                event["article_id"] = "post_1"
                raise ValueError("boom")
        record = _written(events_to_tmp)[0]
        assert record["outcome"] == "error"
        assert record["error_type"] == "ValueError"
        assert record["error"] == "boom"
        assert record["article_id"] == "post_1", "fields set before the failure must survive"

    def test_add_accumulates_without_initialising(self, events_to_tmp):
        with Event("run") as event:
            event.add("llm_calls")
            event.add("llm_calls")
            event.add("llm_cost_usd", 0.5)
        record = _written(events_to_tmp)[0]
        assert record["llm_calls"] == 2 and record["llm_cost_usd"] == 0.5

    def test_an_unserialisable_field_does_not_break_the_run(self, events_to_tmp):
        with Event("article") as event:
            event["weird"] = object()
        assert _written(events_to_tmp)[0]["weird"].startswith("<object")

    def test_emit_never_raises(self, monkeypatch):
        import events as module

        monkeypatch.setattr(module, "_writer", lambda: (_ for _ in ()).throw(OSError("disk full")))
        assert emit({"event": "run"}) == {"event": "run"}

    def test_two_events_in_one_process_share_a_run_id(self, events_to_tmp):
        with Event("run"):
            pass
        with Event("article"):
            pass
        first, second = _written(events_to_tmp)
        assert first["run_id"] == second["run_id"]


class TestHelpers:
    def test_sha8_is_stable_and_short(self):
        assert sha8("Test Article") == sha8("Test Article")
        assert len(sha8("Test Article")) == 8
        assert sha8(None) is None

    def test_sha8_does_not_leak_the_text(self):
        assert "Test Article" not in sha8("Test Article")

    def test_logfmt_quotes_only_what_needs_it(self):
        line = logfmt({"event": "run", "error": "it broke badly", "ok": True, "n": 3})
        assert "event=run" in line
        assert 'error="it broke badly"' in line
        assert "ok=true" in line
        assert "n=3" in line

    def test_logfmt_drops_empty_fields(self):
        assert "error" not in logfmt({"event": "run", "error": None})

    def test_environment_reports_the_code_identity(self):
        env = environment()
        assert set(env) >= {"commit", "git_dirty", "host", "python", "platform", "argv"}


def _run(run_id, ts="2026-08-25T07:00:00Z", **fields):
    return {"event": "run", "run_id": run_id, "ts": ts, "outcome": "ok", **fields}


def _article(run_id, **fields):
    base = {"event": "article", "run_id": run_id, "outcome": "ok", "mode": "digest",
            "has_footer": True, "has_post_date": True}
    base.update(fields)
    return base


class TestSplitting:
    def test_run_order_is_first_appearance(self):
        events = [_run("a"), _article("a"), _run("b"), _article("b")]
        assert run_order(events) == ["a", "b"]

    def test_latest_is_the_last_run_only(self):
        events = [_run("a"), _article("a"), _run("b"), _article("b")]
        latest, baseline = split_latest(events)
        assert {e["run_id"] for e in latest} == {"b"}
        assert {e["run_id"] for e in baseline} == {"a"}

    def test_baseline_is_capped(self):
        events = [e for n in range(30) for e in (_run(f"r{n}"), _article(f"r{n}"))]
        _, baseline = split_latest(events, baseline_runs=5)
        assert len(run_order(baseline)) == 5

    def test_a_single_run_has_no_baseline(self):
        latest, baseline = split_latest([_run("a"), _article("a")])
        assert baseline == [] and len(latest) == 2

    def test_no_events_is_not_a_crash(self):
        assert split_latest([]) == ([], [])


class TestFlagRegressions:
    def test_a_flag_that_stopped_holding_is_a_regression(self):
        baseline = [_article("a") for _ in range(10)]
        latest = [_article("b", has_footer=False)]
        findings = flag_regressions(latest, baseline)
        assert [f["what"] for f in findings] == ["has_footer"]
        assert findings[0]["severity"] == "regression"

    def test_a_flag_that_still_holds_is_silent(self):
        assert flag_regressions([_article("b")], [_article("a") for _ in range(10)]) == []

    def test_a_flag_that_was_never_reliable_is_not_a_regression(self):
        baseline = [_article("a", has_post_date=n % 2 == 0) for n in range(10)]
        assert not any(f["what"] == "has_post_date"
                       for f in flag_regressions([_article("b", has_post_date=False)], baseline))

    def test_no_baseline_means_no_verdict(self):
        assert flag_regressions([_article("b", has_footer=False)], []) == []


class TestNumberShifts:
    def test_a_large_drop_is_flagged(self):
        baseline = [_article("a", notification_chars=600) for _ in range(5)]
        latest = [_article("b", notification_chars=200)]
        findings = number_shifts(latest, baseline)
        assert [f["what"] for f in findings] == ["notification_chars"]
        assert "-67%" in findings[0]["detail"]

    def test_a_small_move_is_ignored(self):
        baseline = [_article("a", topics=3) for _ in range(5)]
        assert number_shifts([_article("b", topics=3)], baseline) == []

    def test_too_little_history_stays_quiet(self):
        assert number_shifts([_article("b", topics=9)], [_article("a", topics=1)]) == []


class TestFailures:
    def test_an_errored_event_is_a_regression(self):
        findings = failures([_article("b", outcome="error", error="boom")])
        assert findings[0]["severity"] == "regression" and "boom" in findings[0]["detail"]

    def test_an_incomplete_event_is_a_warning(self):
        findings = failures([_article("b", outcome="incomplete", skipped="unreadable_body")])
        assert findings[0]["severity"] == "warn"
        assert "unreadable_body" in findings[0]["detail"]


class TestConfigChanges:
    def test_a_changed_prompt_is_reported_as_context(self):
        baseline = [_run("a", prompt_sha="aaaa1111") for _ in range(3)]
        latest = [_run("b", prompt_sha="bbbb2222")]
        findings = config_changes(latest, baseline)
        assert findings[0]["what"] == "prompt_sha"
        assert findings[0]["severity"] == "info"
        assert "aaaa1111 -> bbbb2222" in findings[0]["detail"]

    def test_a_dirty_tree_is_a_warning(self):
        findings = config_changes([_run("b", git_dirty=True)], [_run("a", git_dirty=False)])
        assert any(f["what"] == "git_dirty" and f["severity"] == "warn" for f in findings)


class TestReview:
    def test_the_footer_regression_is_found_end_to_end(self):
        events = [e for n in range(10) for e in (_run(f"r{n}"), _article(f"r{n}"))]
        events += [_run("bad", prompt_sha="changed"), _article("bad", has_footer=False)]
        findings = review(events)["findings"]
        assert any(f["what"] == "has_footer" and f["severity"] == "regression" for f in findings)
        assert any(f["what"] == "prompt_sha" for f in findings), "the likely cause is shown too"

    def test_a_healthy_run_reports_nothing(self):
        events = [e for n in range(10) for e in (_run(f"r{n}"), _article(f"r{n}"))]
        events += [_run("good"), _article("good")]
        assert review(events)["findings"] == []


class TestLoading:
    def test_reads_what_event_wrote(self, events_to_tmp):
        with Event("run") as event:
            event["articles_seen"] = 3
        assert load_events(str(events_to_tmp))[0]["articles_seen"] == 3

    def test_a_missing_file_is_empty(self, tmp_path):
        assert load_events(str(tmp_path / "absent.jsonl")) == []

    def test_a_torn_line_is_skipped_not_fatal(self, tmp_path):
        path = tmp_path / "events.jsonl"
        path.write_text('{"event":"run"}\n{"event":"tru\n{"event":"article"}\n', encoding="utf-8")
        assert [e["event"] for e in load_events(str(path))] == ["run", "article"]
