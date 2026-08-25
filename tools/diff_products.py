"""Show what actually changed in the notifications between two runs.

A score that moved tells you something moved; it never tells you which
sentence. `product.json` is overwritten every run, so `run_digest` keeps a dated
copy of each one and this reads two of them back.

Compares the rendered notification — the text a parent receives — not the digest
JSON, because a reordered key is not a change anyone can see.

Everything here quotes real posts. Read it, never commit it.
"""
import argparse
import difflib
import glob
import json
import os
import sys

from rich.markup import escape

from socialschools.console import console, new_table
from socialschools.paths import HISTORY_DIR


def archived_products(directory=None):
    """Every archived product, oldest first."""
    directory = directory or HISTORY_DIR
    return sorted(glob.glob(os.path.join(directory, "*.json")))


def load_product(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def notifications(product):
    """{case id: delivered notification} for every case that produced one."""
    return {
        case["id"]: (case.get("product") or {}).get("notification", "")
        for case in product.get("cases", [])
    }


def label(product, path):
    variant = product.get("variant", {})
    effort = variant.get("reasoning_effort")
    model = variant.get("model") or "default"
    return "%s%s  prompt=%s  %s" % (
        model, f"@{effort}" if effort else "",
        product.get("prompt_sha", "?"), os.path.basename(path))


def compare(before, after):
    """Per case: character counts either side, and whether the text moved."""
    rows = []
    for case_id in sorted(set(before) | set(after)):
        old, new = before.get(case_id), after.get(case_id)
        rows.append({
            "id": case_id,
            "before": None if old is None else len(old),
            "after": None if new is None else len(new),
            "changed": old != new,
        })
    return rows


def print_summary(rows, before_label, after_label):
    console.print(f"[muted]before:[/muted] {escape(before_label)}")
    console.print(f"[muted]after :[/muted] {escape(after_label)}\n")

    table = new_table("case", ("before", "right"), ("after", "right"),
                      ("delta", "right"), "changed", title="Notification length")
    for row in rows:
        before, after = row["before"], row["after"]
        if before is None or after is None:
            delta, style = "-", "warn"
        else:
            delta = f"{after - before:+d}"
            style = "ok" if after <= before else "warn"
        table.add_row(
            row["id"],
            "-" if before is None else str(before),
            "-" if after is None else str(after),
            f"[{style}]{delta}[/{style}]",
            "yes" if row["changed"] else "[muted]no[/muted]",
        )
    console.print(table)

    changed = sum(1 for row in rows if row["changed"])
    sized = [row for row in rows if row["before"] is not None and row["after"] is not None]
    if sized:
        total_before = sum(row["before"] for row in sized)
        total_after = sum(row["after"] for row in sized)
        console.print(
            f"\n{changed}/{len(rows)} case(s) changed; "
            f"total {total_before} -> {total_after} characters "
            f"({total_after - total_before:+d})")


def print_case_diff(case_id, before, after):
    old = before.get(case_id)
    new = after.get(case_id)
    if old is None and new is None:
        console.print(f"[bad]No case {case_id!r} in either run.[/bad]")
        return 2
    if old == new:
        console.print(f"[ok]{case_id} is unchanged.[/ok]")
        return 0

    diff = difflib.unified_diff(
        (old or "").splitlines(), (new or "").splitlines(),
        fromfile="before", tofile="after", lineterm="", n=2)
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            console.print(f"[ok]{escape(line)}[/ok]")
        elif line.startswith("-") and not line.startswith("---"):
            console.print(f"[bad]{escape(line)}[/bad]")
        elif line.startswith("@@"):
            console.print(f"[muted]{escape(line)}[/muted]")
        else:
            console.print(escape(line))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", default=HISTORY_DIR)
    parser.add_argument("--case", help="show a full diff for one case id")
    parser.add_argument("--before", help="path to the earlier product (default: second newest)")
    parser.add_argument("--after", help="path to the later product (default: newest)")
    parser.add_argument("--list", action="store_true", help="list archived runs and exit")
    args = parser.parse_args(argv)

    archived = archived_products(args.history)
    if args.list:
        for path in archived:
            console.print(f"{os.path.basename(path)}  {label(load_product(path), path)}")
        return 0

    before_path = args.before or (archived[-2] if len(archived) >= 2 else None)
    after_path = args.after or (archived[-1] if archived else None)
    if not before_path or not after_path:
        console.print(
            "[bad]Need two archived products to compare; "
            f"found {len(archived)} in {args.history}.[/bad]")
        console.print("[muted]Run `make product` at least twice.[/muted]")
        return 2

    before_product, after_product = load_product(before_path), load_product(after_path)
    before, after = notifications(before_product), notifications(after_product)

    if args.case:
        return print_case_diff(args.case, before, after)

    print_summary(compare(before, after),
                  label(before_product, before_path),
                  label(after_product, after_path))
    console.print("[warn]These quote real posts: personal data. Never commit them.[/warn]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
