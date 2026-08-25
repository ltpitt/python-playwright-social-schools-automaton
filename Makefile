.PHONY: help install install-dev lint test check run health events clean \
        corpus product eval eval-cycle bakeoff goal unprocess-last diff

PYTHON ?= python

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  install      Install runtime dependencies"
	@echo "  install-dev  Install runtime + development dependencies"
	@echo "  lint         flake8 over the package, the harness and the tests"
	@echo "  test         Run the pytest suite"
	@echo "  check        lint + test + import sanity (CI gate)"
	@echo "  run          Run the application (needs var/config.ini)"
	@echo ""
	@echo "  corpus          Update the local corpus with new posts and attachments"
	@echo "  product         Generate the product JSON from the local corpus"
	@echo "  eval            Evaluate the product (judges phrases the matcher missed)"
	@echo "  diff            What changed in the notifications since the run before"
	@echo "  eval-cycle      Pull, regenerate, send one live notification, then evaluate"
	@echo "  bakeoff         Compare models on quality vs cost: make bakeoff MODELS='a b@high'"
	@echo "  goal            Rewrite the prompt until the holdout gate passes: make goal TURNS=5"
	@echo "  unprocess-last  Forget the last processed article so 'make run' re-sends it"
	@echo ""
	@echo "  health       Compare the last run against the ones before it"
	@echo "  events       Show the last 20 runs from the event log"
	@echo "  clean        Remove Python cache directories"

install:
	$(PYTHON) -m pip install -r requirements.txt

install-dev:
	$(PYTHON) -m pip install -r requirements-dev.txt

# Errors are fatal; style is advisory. Everything is linted, including the goal
# loop, which is the one program here that edits a file unattended.
lint:
	$(PYTHON) -m flake8 socialschools tools tests --count --select=E9,F63,F7,F82 --show-source --statistics
	$(PYTHON) -m flake8 socialschools tools tests --count --exit-zero --statistics

test:
	$(PYTHON) -m pytest -v

check: lint test
	$(PYTHON) -c "import socialschools.pipeline; print('Import OK')"

# Run the application. Add ARGS='--force -v' to pass flags through.
run:
	$(PYTHON) -m socialschools $(ARGS)

# Update the local source corpus. Its output is personal data and lives in var/.
corpus:
	$(PYTHON) -m tools.build_corpus

# Run the real digest flow without sending notifications.
# SAMPLES>1 regenerates each case to expose run-to-run instability.
product:
	$(PYTHON) -m tools.run_digest $(if $(FORCE),--force,) $(if $(MODEL),--model $(MODEL),) \
		$(if $(REASONING),--reasoning $(REASONING),) $(if $(SAMPLES),--samples $(SAMPLES),)

# Evaluate the exact product written by the product target.
# Gates on every case; GATE=holdout gates only on the cases the prompt was not
# tuned against. A missed phrase gets a second opinion before it counts as
# missed; NOJUDGE=1 for a fully offline, fully deterministic run.
eval:
	$(PYTHON) -m tools.evaluate_digests --summary var/eval/summary.json $(if $(GATE),--gate-on $(GATE),) \
		$(if $(NOJUDGE),--no-judge,) $(if $(JUDGE_MODEL),--judge-model $(JUDGE_MODEL),)

# Is the cheap model good enough? Replay the corpus through each model and
# compare quality against real money. Costs money: every case is regenerated.
bakeoff:
	@test -n "$(MODELS)" || { echo "Usage: make bakeoff MODELS='model-a model-b@medium'"; exit 2; }
	$(PYTHON) -m tools.bakeoff $(MODELS) $(if $(SAMPLES),--samples $(SAMPLES),)

# Which sentence moved? A score tells you something changed and never what.
# CASE=post_123 shows the full before/after for one case.
diff:
	$(PYTHON) -m tools.diff_products $(if $(CASE),--case $(CASE),) $(if $(LIST),--list,)

# Close the loop: rewrite the digest prompt until the holdout gate passes or the
# turns run out. Costs money (every turn regenerates every case) and commits
# nothing. Never part of 'make check'.
goal:
	$(PYTHON) -m tools.goal $(if $(TURNS),--turns $(TURNS),) $(if $(PATIENCE),--patience $(PATIENCE),) \
		$(if $(IMPROVER_MODEL),--improver-model $(IMPROVER_MODEL),)

# Did anything get worse? Compares the last run's canonical events against the
# runs before it. Reads only, costs nothing, no model involved.
health:
	$(PYTHON) -m tools.check_events $(if $(BASELINE),--baseline-runs $(BASELINE),)

# Complete cycle. Eval runs last so its table is the final output, ready to copy.
# Neither leg short-circuits the other, but both failures still surface.
# Health runs in between: it reads the events the live run just wrote and says
# whether anything about production got worse, which the corpus eval cannot see.
eval-cycle:
	@set -e; \
	git pull --ff-only; \
	$(MAKE) corpus; \
	$(MAKE) product FORCE=1; \
	$(MAKE) unprocess-last; \
	set +e; \
	$(MAKE) run; \
	run_status=$$?; \
	$(MAKE) health; \
	health_status=$$?; \
	$(MAKE) eval; \
	eval_status=$$?; \
	set -e; \
	if [ $$run_status -ne 0 ]; then exit $$run_status; fi; \
	if [ $$health_status -ne 0 ]; then exit $$health_status; fi; \
	exit $$eval_status

# Drop the most recently processed article so the next 'make run' re-scrapes,
# re-generates and re-sends its real notification (for eyeballing prompt changes).
unprocess-last:
	@$(PYTHON) -c "import json, os; \
from socialschools.paths import PROCESSED_ARTICLES_FILE as p; \
d = json.load(open(p)) if os.path.exists(p) else []; \
removed = d.pop() if d else None; \
json.dump(d, open(p, 'w')) if removed else None; \
print(f'Removed {removed}; next run will re-process it' if removed else 'Nothing to remove')"

# One line per run, newest last. Everything else is a jq query away.
# Needs jq and column; both are dev conveniences, not runtime dependencies.
events:
	@test -f var/logs/events.jsonl || { echo "No events yet — run the app once."; exit 0; }
	@jq -r 'select(.event=="run") | [.ts, .run_id, .outcome, .commit, (.articles_processed//0), \
		(.llm_cost_usd//0), .model] | @tsv' var/logs/events.jsonl | tail -20 | \
		column -t -s "$$(printf '\t')"

# Cache artefacts only. Nothing under var/ is touched: it is the evidence.
clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -prune -exec rm -rf {} + 2>/dev/null || true
