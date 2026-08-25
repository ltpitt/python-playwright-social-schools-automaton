"""Read the canonical events back and say whether the system got worse.

The events are the fuel; this is one engine. It compares the most recent run
against the runs before it and reports what changed — a flag that used to be
true and now is not, a number that moved, an article that failed. The footer
that silently vanished from every notification is exactly the class of fault it
exists to catch, and the reason it can catch it is that the event records the
*shape* of what was produced, not just that something was produced.

It also prints what changed about the run itself — commit, model, prompt — next
to what changed about the output, because those are the causes worth suspecting
first and the event happens to carry both.

Reads only. Costs nothing. Safe to run after every cycle.
"""
import argparse
import json
import os
import statistics
import sys
from collections import Counter

from console import console, new_table

DEFAULT_EVENTS = "events.jsonl"
# Enough history for a median to mean something, short enough to still be "lately".
DEFAULT_BASELINE_RUNS = 20

# Flags that should essentially always hold. One of these going false is the
# signal; everything else here is context for it.
WATCHED_FLAGS = ("has_footer", "has_post_date")
# Numbers whose shape says something about digest quality.
WATCHED_NUMBERS = ("notification_chars", "topics", "actions", "bring", "notes", "tldr_chars")
# Run-level facts that explain a change rather than being one.
WATCHED_CONFIG = ("commit", "model", "prompt_sha", "provider", "structured_output",
                  "digest_enabled", "reasoning_effort")

_FLAG_BASELINE_MIN = 0.9
_NUMBER_SHIFT = 0.4


def load_events(path=DEFAULT_EVENTS):
    """Every event ever written, oldest first. Unparseable lines are skipped."""
    if not os.path.exists(path):
        return []
    events = []
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    return events


def run_order(events):
    """Run ids in the order they first appear, so 'latest' means latest."""
    seen = []
    for event in events:
        run_id = event.get("run_id")
        if run_id and run_id not in seen:
            seen.append(run_id)
    return seen


def split_latest(events, baseline_runs=DEFAULT_BASELINE_RUNS):
    """(latest run's events, the events of the runs before it)."""
    order = run_order(events)
    if not order:
        return [], []
    latest_id = order[-1]
    baseline_ids = set(order[max(0, len(order) - 1 - baseline_runs):-1])
    latest = [e for e in events if e.get("run_id") == latest_id]
    baseline = [e for e in events if e.get("run_id") in baseline_ids]
    return latest, baseline


def _articles(events):
    return [e for e in events if e.get("event") == "article" and e.get("mode") == "digest"]


def _values(events, field):
    return [e[field] for e in events if isinstance(e.get(field), (int, float))
            and not isinstance(e.get(field), bool)]


def _flags(events, field):
    return [e[field] for e in events if isinstance(e.get(field), bool)]


def flag_regressions(latest, baseline):
    """Flags that used to hold and stopped holding."""
    findings = []
    for field in WATCHED_FLAGS:
        was = _flags(baseline, field)
        now = _flags(latest, field)
        if not was or not now:
            continue
        rate = sum(was) / len(was)
        broken = sum(1 for value in now if not value)
        if rate >= _FLAG_BASELINE_MIN and broken:
            findings.append({
                "severity": "regression",
                "what": field,
                "detail": f"true in {rate:.0%} of {len(was)} earlier article(s), "
                          f"false in {broken}/{len(now)} now",
            })
    return findings


def number_shifts(latest, baseline):
    """Numbers whose typical value moved enough to be worth a look."""
    findings = []
    for field in WATCHED_NUMBERS:
        was = _values(baseline, field)
        now = _values(latest, field)
        if len(was) < 3 or not now:
            continue
        before, after = statistics.median(was), statistics.median(now)
        if before <= 0:
            continue
        change = (after - before) / before
        if abs(change) >= _NUMBER_SHIFT:
            findings.append({
                "severity": "warn",
                "what": field,
                "detail": f"median {before:g} -> {after:g} ({change:+.0%})",
            })
    return findings


def failures(latest):
    findings = []
    for event in latest:
        outcome = event.get("outcome")
        if outcome and outcome != "ok":
            findings.append({
                "severity": "regression" if outcome == "error" else "warn",
                "what": f"{event.get('event')} {outcome}",
                "detail": event.get("error") or event.get("skipped") or "",
            })
    return findings


def config_changes(latest, baseline):
    """What is different about this run, as candidate causes."""
    latest_run = next((e for e in latest if e.get("event") == "run"), None)
    baseline_runs = [e for e in baseline if e.get("event") == "run"]
    if not latest_run or not baseline_runs:
        return []
    findings = []
    for field in WATCHED_CONFIG:
        previous = Counter(str(run.get(field)) for run in baseline_runs).most_common(1)
        if not previous:
            continue
        was = previous[0][0]
        now = str(latest_run.get(field))
        if was != now:
            findings.append({"severity": "info", "what": field, "detail": f"{was} -> {now}"})
    if latest_run.get("git_dirty"):
        findings.append({"severity": "warn", "what": "git_dirty",
                         "detail": "uncommitted changes — this run is not any known commit"})
    return findings


def review(events, baseline_runs=DEFAULT_BASELINE_RUNS):
    latest, baseline = split_latest(events, baseline_runs)
    latest_articles, baseline_articles = _articles(latest), _articles(baseline)
    return {
        "latest": latest,
        "baseline_runs": len(run_order(baseline)),
        "findings": (failures(latest)
                     + flag_regressions(latest_articles, baseline_articles)
                     + number_shifts(latest_articles, baseline_articles)
                     + config_changes(latest, baseline)),
    }


_STYLES = {"regression": "bad", "warn": "warn", "info": "muted"}


def print_review(result):
    latest_run = next((e for e in result["latest"] if e.get("event") == "run"), None)
    if latest_run:
        console.print(f"[head]Latest run[/head] {latest_run.get('run_id')} "
                      f"[muted]{latest_run.get('ts')} commit={latest_run.get('commit')} "
                      f"model={latest_run.get('model')}[/muted]")
    console.print(f"[muted]Compared against the {result['baseline_runs']} run(s) before it[/muted]")

    if not result["findings"]:
        console.print("\n[ok]Nothing changed for the worse.[/ok]")
        return
    table = new_table("severity", "what", "detail", title="Findings")
    for finding in result["findings"]:
        style = _STYLES.get(finding["severity"], "muted")
        table.add_row(f"[{style}]{finding['severity']}[/{style}]",
                      finding["what"], finding["detail"])
    console.print(table)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", default=DEFAULT_EVENTS)
    parser.add_argument("--baseline-runs", type=int, default=DEFAULT_BASELINE_RUNS)
    args = parser.parse_args()

    events = load_events(args.events)
    if not events:
        console.print(f"[warn]No events at {args.events} yet — run the app once.[/warn]")
        return
    result = review(events, args.baseline_runs)
    print_review(result)
    sys.exit(1 if any(f["severity"] == "regression" for f in result["findings"]) else 0)


if __name__ == "__main__":
    main()
