.PHONY: help install lint test check run loop goal clean corpus product eval eval-cycle bakeoff unprocess-last

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  install  Install Python dependencies"
	@echo "  lint     flake8 strict + full style check"
	@echo "  test     Run pytest suite"
	@echo "  check    lint + test + import sanity (CI gate)"
	@echo "  run      Run the main script (requires config.ini)"
	@echo "  corpus      Update corpus with new posts and attachments"
	@echo "  product     Generate product JSON from the local corpus"
	@echo "  eval        Evaluate the product JSON (does not call the model)"
	@echo "  eval-cycle  Pull, regenerate, send one live notification, then evaluate"
	@echo "  bakeoff     Compare models on quality vs cost: make bakeoff MODELS='a b@high'"
	@echo "  unprocess-last  Forget the last processed article so 'make run' re-sends it"
	@echo "  loop     Clear loop_output.md and run one loop.sh iteration"
	@echo "  goal     Rewrite the prompt until the holdout gate passes: make goal TURNS=5"
	@echo "  clean    Remove Python cache directories"

# Install Python dependencies
install:
	pip install -r requirements.txt

# Strict lint — errors only (CI gate)
lint:
	flake8 get_social_schools_news.py --count --select=E9,F63,F7,F82 --show-source --statistics
	flake8 get_social_schools_news.py --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics

# Run test suite
test:
	pytest -v

# Quick sanity: lint + test + import check
check: lint test
	python -c "import get_social_schools_news; print('Import OK')"

# Run the main script (requires valid config.ini)
run:
	python get_social_schools_news.py

# Update the local source corpus. Output is personal data and gitignored.
corpus:
	python build_corpus.py

# Run the real digest flow without sending notifications.
# SAMPLES>1 regenerates each case to expose run-to-run instability.
product:
	python run_digest.py $(if $(FORCE),--force,) $(if $(MODEL),--model $(MODEL),) \
		$(if $(REASONING),--reasoning $(REASONING),) $(if $(SAMPLES),--samples $(SAMPLES),)

# Evaluate the exact product written by the product target.
# Gates on every case; GATE=holdout gates only on the cases the prompt was not tuned against.
eval:
	python evaluate_digests.py --summary eval_output/summary.json $(if $(GATE),--gate-on $(GATE),)

# Is the cheap model good enough? Replay the corpus through each model and
# compare quality against real money. Costs money: every case is regenerated.
bakeoff:
	@test -n "$(MODELS)" || { echo "Usage: make bakeoff MODELS='model-a model-b@medium'"; exit 2; }
	python bakeoff.py $(MODELS) $(if $(SAMPLES),--samples $(SAMPLES),)

# Complete cycle. Eval runs last so its table is the final output, ready to copy.
# Neither leg short-circuits the other, but both failures still surface.
eval-cycle:
	@set -e; \
	git pull --ff-only; \
	$(MAKE) corpus; \
	$(MAKE) product FORCE=1; \
	$(MAKE) unprocess-last; \
	set +e; \
	$(MAKE) run; \
	run_status=$$?; \
	$(MAKE) eval; \
	eval_status=$$?; \
	set -e; \
	if [ $$run_status -ne 0 ]; then exit $$run_status; fi; \
	exit $$eval_status

# Drop the most recently processed article so the next 'make run' re-scrapes,
# re-generates and re-sends its real notification (for eyeballing prompt changes).
unprocess-last:
	python -c "import json; p='processed_articles.json'; d=json.load(open(p)) if __import__('os').path.exists(p) else []; removed=d.pop() if d else None; json.dump(d, open(p, 'w')); print(f'Removed {removed}; next run will re-process it' if removed else 'Nothing to remove')"

# Run one loop iteration — clears previous output first
loop:
	> loop_output.md
	./loop.sh

# Close the loop: rewrite digest_prompt.txt until the holdout gate passes or the
# turns run out. Costs money (every turn regenerates every case) and commits
# nothing. Never in 'make check'.
goal:
	python goal.py $(if $(TURNS),--turns $(TURNS),) $(if $(PATIENCE),--patience $(PATIENCE),) \
		$(if $(IMPROVER_MODEL),--improver-model $(IMPROVER_MODEL),)

# Remove Python cache artefacts (run_report.txt / full_prompt.txt / loop_output.md are kept for inspection)
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
