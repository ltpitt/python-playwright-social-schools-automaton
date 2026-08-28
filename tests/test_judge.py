import json
from unittest.mock import patch

import pytest

from tools.evaluate_digests import apply_rescues
from tools.judge import _key, build_prompt, load_cache, parse_verdicts, save_cache, verdicts


def _result(case_id, missing, hits=0, total=None):
    return {
        "id": case_id,
        "recall_missing": list(missing),
        "recall_hits": hits,
        "recall_total": total if total is not None else hits + len(missing),
    }


class TestPromptAndParsing:
    def test_prompt_numbers_each_phrase_and_fences_the_summary(self):
        prompt = build_prompt("Bring a towel on 01 Sep.", ["towel", "01 Sep"])
        assert "1. towel" in prompt and "2. 01 Sep" in prompt
        assert "--- SUMMARY START ---" in prompt
        assert "Bring a towel on 01 Sep." in prompt
        assert "untrusted school website" in prompt

    def test_numbers_map_back_onto_phrases(self):
        parsed = parse_verdicts('{"1": true, "2": false}', ["group division", "library"])
        assert parsed == {"group division": True, "library": False}

    def test_non_boolean_answers_are_ignored(self):
        assert parse_verdicts('{"1": "yes", "2": true}', ["a", "b"]) == {"b": True}

    def test_prose_around_the_json_is_tolerated(self):
        assert parse_verdicts('Sure!\n{"1": true}\n', ["a"]) == {"a": True}

    def test_a_non_object_answer_raises(self):
        with pytest.raises(ValueError):
            parse_verdicts("[true]", ["a"])


class TestVerdicts:
    def test_no_phrases_means_no_call(self):
        with patch("tools.judge._ask", side_effect=AssertionError("must not be called")):
            assert verdicts("digest", [], model="m", cache={}) == {}

    def test_a_cached_verdict_is_not_asked_again(self):
        cache = {_key("m", "digest", "towel"): True}
        with patch("tools.judge._ask", side_effect=AssertionError("must not be called")):
            assert verdicts("digest", ["towel"], model="m", cache=cache) == {"towel": True}

    def test_a_fresh_verdict_is_cached(self):
        cache = {}
        with patch("tools.judge._ask", return_value='{"1": true}'):
            verdicts("digest", ["towel"], model="m", cache=cache)
        assert cache[_key("m", "digest", "towel")] is True

    def test_only_the_uncached_phrases_are_asked_about(self):
        cache = {_key("m", "digest", "towel"): True}
        with patch("tools.judge._ask", return_value='{"1": false}') as ask:
            result = verdicts("digest", ["towel", "library"], model="m", cache=cache)
        assert "library" in ask.call_args[0][0]
        assert "towel" not in ask.call_args[0][0]
        assert result == {"towel": True, "library": False}

    def test_an_unreachable_judge_rescues_nothing(self):
        with patch("tools.judge._ask", side_effect=RuntimeError("offline")):
            assert verdicts("digest", ["towel"], model="m", cache={}) == {}

    def test_an_incoherent_judge_rescues_nothing(self):
        with patch("tools.judge._ask", return_value="I'm not sure, sorry"):
            assert verdicts("digest", ["towel"], model="m", cache={}) == {}

    def test_the_digest_schema_is_off_while_judging(self):
        from socialschools.config import get_config
        from tools.judge import _ask

        cfg = get_config()
        cfg.LLM_STRUCTURED_OUTPUT = True
        seen = {}

        class FakeProvider:
            def complete(self, prompt):
                seen["structured"] = get_config().LLM_STRUCTURED_OUTPUT
                return '{"1": true}'

        with patch("tools.judge.get_provider", return_value=FakeProvider()):
            _ask("prompt", "some/model")
        assert seen["structured"] is False
        assert cfg.LLM_STRUCTURED_OUTPUT is True


class TestCacheFile:
    def test_round_trips(self, tmp_path):
        path = str(tmp_path / "nested" / "judge_cache.json")
        save_cache({"abc": True}, path)
        assert load_cache(path) == {"abc": True}

    def test_a_missing_file_is_an_empty_cache(self, tmp_path):
        assert load_cache(str(tmp_path / "absent.json")) == {}

    def test_a_corrupt_file_is_an_empty_cache(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        assert load_cache(str(path)) == {}

    def test_the_key_separates_models(self):
        assert _key("model-a", "digest", "towel") != _key("model-b", "digest", "towel")


class TestApplyRescues:
    def test_a_rescued_phrase_becomes_a_hit(self):
        results = [_result("post_1", ["group division"], hits=1)]
        apply_rescues(results, {"post_1": "group assignments are attached"},
                      lambda text, phrases: {"group division": True})
        assert results[0]["recall_missing"] == []
        assert results[0]["recall_hits"] == 2
        assert results[0]["recall_rescued"] == ["group division"]

    def test_a_refused_phrase_stays_missing(self):
        results = [_result("post_1", ["library"], hits=0)]
        apply_rescues(results, {"post_1": "nothing about books"},
                      lambda text, phrases: {"library": False})
        assert results[0]["recall_missing"] == ["library"]
        assert results[0]["recall_hits"] == 0
        assert "recall_rescued" not in results[0]

    def test_a_passing_case_is_never_put_to_the_judge(self):
        results = [_result("post_1", [], hits=3)]

        def explode(text, phrases):
            raise AssertionError("must not be called")

        apply_rescues(results, {}, explode)
        assert results[0]["recall_hits"] == 3

    def test_a_silent_judge_changes_nothing(self):
        results = [_result("post_1", ["towel"], hits=1)]
        apply_rescues(results, {"post_1": "text"}, lambda text, phrases: {})
        assert results[0]["recall_missing"] == ["towel"]
        assert results[0]["recall_hits"] == 1

    def test_only_some_phrases_rescued(self):
        results = [_result("post_1", ["group 3", "library"], hits=1)]
        apply_rescues(results, {"post_1": "groups 3 and 4"},
                      lambda text, phrases: {"group 3": True, "library": False})
        assert results[0]["recall_missing"] == ["library"]
        assert results[0]["recall_hits"] == 2

    def test_the_judge_sees_the_rendered_notification(self):
        results = [_result("post_1", ["towel"], hits=0)]
        seen = {}

        def spy(text, phrases):
            seen["text"] = text
            return {}

        apply_rescues(results, {"post_1": "Bring a hand cloth"}, spy)
        assert seen["text"] == "Bring a hand cloth"

    def test_a_rescue_can_turn_a_failing_case_into_a_passing_one(self):
        from tools.evaluate_digests import case_passed

        result = _result("post_1", ["group division"], hits=1)
        result["violations"] = []
        assert not case_passed(result, 1.0)
        apply_rescues([result], {"post_1": "group assignments"},
                      lambda text, phrases: {"group division": True})
        assert case_passed(result, 1.0)

    def test_a_rescue_can_never_fail_a_passing_case(self):
        from tools.evaluate_digests import case_passed

        result = _result("post_1", [], hits=2)
        result["violations"] = []
        apply_rescues([result], {"post_1": "text"},
                      lambda text, phrases: {"anything": False})
        assert case_passed(result, 1.0)


def test_cache_file_is_json_serialisable(tmp_path):
    cache = {}
    with patch("tools.judge._ask", return_value='{"1": true, "2": false}'):
        verdicts("digest text", ["towel", "library"], model="m", cache=cache)
    path = str(tmp_path / "cache.json")
    save_cache(cache, path)
    assert json.loads(open(path, encoding="utf-8").read()) == cache
