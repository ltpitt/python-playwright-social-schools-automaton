"""Comparing two archived products.

The point of these is that a score which moved can be traced back to the text
that moved. Invented notifications only.
"""
import json

from tools import diff_products


def _product(notifications, model="test-model", prompt_sha="abc12345"):
    return {
        "schema_version": 3,
        "generated_at": "2026-08-25T13:00:00.000+00:00",
        "variant": {"model": model, "reasoning_effort": ""},
        "prompt_sha": prompt_sha,
        "cases": [
            {"id": case_id, "product": {"notification": text}}
            for case_id, text in notifications.items()
        ],
    }


def _write(directory, name, product):
    path = directory / name
    path.write_text(json.dumps(product), encoding="utf-8")
    return str(path)


def test_notifications_reads_the_delivered_text():
    product = _product({"post_1": "Bring a towel."})
    assert diff_products.notifications(product) == {"post_1": "Bring a towel."}


def test_notifications_tolerates_a_case_that_failed_to_generate():
    product = {"cases": [{"id": "post_1", "product": None}]}
    assert diff_products.notifications(product) == {"post_1": ""}


def test_compare_reports_length_either_side_and_whether_it_moved():
    rows = diff_products.compare(
        {"post_1": "aaa", "post_2": "same"},
        {"post_1": "a", "post_2": "same"})

    by_id = {row["id"]: row for row in rows}
    assert by_id["post_1"] == {"id": "post_1", "before": 3, "after": 1, "changed": True}
    assert by_id["post_2"]["changed"] is False


def test_compare_marks_a_case_missing_from_one_side():
    rows = diff_products.compare({"post_1": "text"}, {})
    assert rows[0]["after"] is None
    assert rows[0]["changed"] is True


def test_archived_products_are_ordered_oldest_first(tmp_path):
    _write(tmp_path, "20260825T1200-aaa-m.json", _product({"post_1": "one"}))
    _write(tmp_path, "20260825T1300-bbb-m.json", _product({"post_1": "two"}))

    found = diff_products.archived_products(str(tmp_path))
    assert [p.split("/")[-1][:13] for p in found] == ["20260825T1200", "20260825T1300"]


def test_main_needs_two_runs_before_it_can_compare(tmp_path, capsys):
    _write(tmp_path, "20260825T1200-aaa-m.json", _product({"post_1": "one"}))
    assert diff_products.main(["--history", str(tmp_path)]) == 2


def test_main_diffs_one_case_between_the_two_newest_runs(tmp_path, capsys):
    _write(tmp_path, "20260825T1200-aaa-m.json",
           _product({"post_1": "Bring a towel.\nArrive at 08:20."}))
    _write(tmp_path, "20260825T1300-bbb-m.json",
           _product({"post_1": "Bring a towel."}))

    assert diff_products.main(["--history", str(tmp_path), "--case", "post_1"]) == 0
    out = capsys.readouterr().out
    assert "Arrive at 08:20." in out


def test_main_says_so_when_a_case_did_not_move(tmp_path, capsys):
    for name in ("20260825T1200-aaa-m.json", "20260825T1300-bbb-m.json"):
        _write(tmp_path, name, _product({"post_1": "Bring a towel."}))

    assert diff_products.main(["--history", str(tmp_path), "--case", "post_1"]) == 0
    assert "unchanged" in capsys.readouterr().out


def test_main_summarises_every_case_when_no_case_is_named(tmp_path, capsys):
    _write(tmp_path, "20260825T1200-aaa-m.json", _product({"post_1": "aaaa", "post_2": "bb"}))
    _write(tmp_path, "20260825T1300-bbb-m.json", _product({"post_1": "aa", "post_2": "bb"}))

    assert diff_products.main(["--history", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "post_1" in out and "post_2" in out
    assert "-2" in out
