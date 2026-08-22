"""Replay one corpus through several LLM variants and compare quality against cost.

Answers one question: is the cheap model good enough, or is the money better
spent on a bigger one? Every variant sees the identical corpus, prompt and
scoring, so the only thing that differs is the model (and optionally its
reasoning effort), which is what makes the comparison worth anything.

A variant is written as `model` or `model@effort`, e.g.

    google/gemini-2.5-flash
    google/gemini-2.5-flash@medium
    google/gemini-2.5-pro

Costs real money: every variant regenerates every case. Outputs quote real
posts, so everything it writes is personal data and stays gitignored.
"""
import argparse
import json
import os
import re

from evaluate_digests import build_summary, evaluate_product_case, load_expectations
from run_digest import DEFAULT_CORPUS, apply_llm_overrides, run_corpus

DEFAULT_OUTPUT_DIR = "eval_output"
DEFAULT_REPORT = "eval_output/bakeoff.json"


def parse_variant(spec):
    model, _, effort = spec.partition("@")
    return {"spec": spec, "model": model.strip(), "reasoning": effort.strip().lower()}


def _slug(spec):
    return re.sub(r"[^a-z0-9]+", "-", spec.lower()).strip("-")


def run_variant(variant, corpus, output_dir, expectations, samples, min_recall):
    apply_llm_overrides(variant["model"], variant["reasoning"])
    slug = _slug(variant["spec"])
    product = run_corpus(
        corpus,
        os.path.join(output_dir, f"product-{slug}.json"),
        os.path.join(output_dir, f"state-{slug}.json"),
        force=True,
        samples=samples,
    )
    results = [evaluate_product_case(case, expectations.get(case["id"], {}))
               for case in product["cases"]]
    summary = build_summary(product, results, min_recall)
    summary["spec"] = variant["spec"]
    return summary


def _cost(summary):
    return summary["usage"].get("cost_usd")


def format_table(summaries):
    lines = [
        f"{'variant':<34} {'holdout':>8} {'tune':>8} {'score':>6} {'recall':>7} "
        f"{'viol':>5} {'warn':>5} {'unstable':>9} {'cost':>9} {'sec/case':>9}",
        "-" * 110,
    ]
    for summary in summaries:
        holdout = summary["splits"]["holdout"]
        tune = summary["splits"]["tune"]
        overall = summary["splits"]["all"]
        cost = _cost(summary)
        cases = overall["cases"] or 1
        seconds = summary["usage"].get("latency_s", 0) / cases
        recall = f"{overall['recall']:.0%}" if overall["recall"] is not None else "n/a"
        lines.append(
            f"{summary['spec']:<34} "
            f"{holdout['passed']:>3}/{holdout['cases']:<4} "
            f"{tune['passed']:>3}/{tune['cases']:<4} "
            f"{overall['score']:>6.2f} "
            f"{recall:>7} {overall['violations']:>5} {overall['warnings']:>5} "
            f"{overall['unstable']:>9} "
            f"{('$%.4f' % cost) if cost is not None else 'n/a':>9} "
            f"{seconds:>9.1f}"
        )
    return "\n".join(lines)


# Below this, a score difference is noise on a corpus of a few dozen cases.
_MEANINGFUL_SCORE_GAIN = 0.02


def format_verdict(summaries):
    """Say what the numbers imply about paying more, in the plainest terms available."""
    if len(summaries) < 2:
        return ""
    baseline = summaries[0]
    base_score = baseline["splits"]["all"]["score"]
    base_pass = baseline["splits"]["all"]["passed"]
    base_cost = _cost(baseline)
    lines = [f"\nAgainst the baseline {baseline['spec']} (score {base_score:.2f}, "
             f"{base_pass} case(s) passing):"]
    for summary in summaries[1:]:
        gained = summary["splits"]["all"]["score"] - base_score
        cost = _cost(summary)
        if cost is None or base_cost is None or base_cost == 0:
            multiple = "cost not reported"
        else:
            multiple = f"{cost / base_cost:.1f}x the cost"
        if gained >= _MEANINGFUL_SCORE_GAIN:
            verdict = f"score {gained:+.2f} for {multiple}"
        elif gained <= -_MEANINGFUL_SCORE_GAIN:
            verdict = f"score {gained:+.2f}, i.e. worse, for {multiple}"
        else:
            verdict = f"no real gain ({gained:+.2f}) for {multiple} — not worth it"
        lines.append(f"  {summary['spec']:<34} {verdict}")
    lines.append(
        "\nJudge on the holdout column: the tuning cases helped write the prompt, "
        "so they flatter it.")
    if all(s["splits"]["all"]["passed"] == s["splits"]["all"]["cases"] for s in summaries):
        lines.append(
            "Every candidate passes every case, so the pass columns say nothing here. "
            "The ranking above is the graded score; a corpus this small cannot justify "
            "an upgrade on a score gap under "
            f"{_MEANINGFUL_SCORE_GAIN:.2f}.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variants", nargs="+", help="model or model@reasoning_effort")
    parser.add_argument("--corpus", default=DEFAULT_CORPUS)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--expectations", default="expectations.json")
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--samples", type=int, default=1,
                        help="generations per case; >1 exposes run-to-run instability")
    parser.add_argument("--min-recall", type=float, default=1.0)
    args = parser.parse_args()

    if not os.path.exists(args.corpus):
        raise SystemExit(f"No corpus at {args.corpus}. Run make corpus first.")
    os.makedirs(args.output_dir, exist_ok=True)
    expectations = load_expectations(args.expectations)

    summaries = []
    for spec in args.variants:
        variant = parse_variant(spec)
        print(f"\n=== {spec} ===")
        summaries.append(
            run_variant(variant, args.corpus, args.output_dir, expectations,
                        args.samples, args.min_recall))

    print("\n" + format_table(summaries))
    print(format_verdict(summaries))

    with open(args.report, "w", encoding="utf-8") as stream:
        json.dump(summaries, stream, indent=2, ensure_ascii=False)
    print(f"\nScorecards written to {args.report}. They quote real posts: never commit them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
