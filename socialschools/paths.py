"""Every location this project reads or writes, decided in one place.

Everything the application produces is either a credential or derived from real
Social Schools posts, so all of it lives under a single ignored directory. One
`var/` in `.gitignore` replaces a dozen individual rules, and a file that has
nowhere else to go cannot end up beside the source by accident.

Set `SOCIALSCHOOLS_VAR` to relocate the whole tree — a test suite pointing it at
a tmpdir gets full isolation without patching anything.

Paths are read through this module (`paths.PROCESSED_ARTICLES_FILE`) rather than
imported by name, so a test can redirect one of them.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VAR = os.environ.get("SOCIALSCHOOLS_VAR") or os.path.join(ROOT, "var")

# Credentials. The example is committed and complete, so a checkout without a
# config.ini still imports, still runs its tests and still fails honestly at login.
CONFIG_FILE = os.path.join(VAR, "config.ini")
EXAMPLE_CONFIG_FILE = os.path.join(ROOT, "config.example.ini")

STATE_DIR = os.path.join(VAR, "state")
LOG_DIR = os.path.join(VAR, "logs")
CORPUS_DIR = os.path.join(VAR, "corpus")
EVAL_DIR = os.path.join(VAR, "eval")
GOAL_DIR = os.path.join(VAR, "goal")

# Which articles have already been delivered. Production, corpus and product
# runs each keep their own, so replaying a corpus never makes the live run
# forget to notify.
PROCESSED_ARTICLES_FILE = os.path.join(STATE_DIR, "processed_articles.json")
PROCESSED_CORPUS_ARTICLES_FILE = os.path.join(STATE_DIR, "processed_corpus_articles.json")
PROCESSED_PRODUCT_ARTICLES_FILE = os.path.join(STATE_DIR, "processed_product_articles.json")

RUN_REPORT_FILE = os.path.join(LOG_DIR, "run_report.txt")
EVENTS_FILE = os.path.join(LOG_DIR, "events.jsonl")

CORPUS_FILE = os.path.join(CORPUS_DIR, "corpus.json")

EXPECTATIONS_FILE = os.path.join(EVAL_DIR, "expectations.json")
PRODUCT_FILE = os.path.join(EVAL_DIR, "product.json")
EVAL_RESULTS_FILE = os.path.join(EVAL_DIR, "results.json")
EVAL_SUMMARY_FILE = os.path.join(EVAL_DIR, "summary.json")
JUDGE_CACHE_FILE = os.path.join(EVAL_DIR, "judge_cache.json")
BAKEOFF_FILE = os.path.join(EVAL_DIR, "bakeoff.json")

GOAL_LEDGER_FILE = os.path.join(GOAL_DIR, "ledger.tsv")


def ensure_parent(path):
    """Create the directory a file is about to be written into. Returns the path."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path
