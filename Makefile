.PHONY: help install lint test check run loop clean corpus product eval eval-cycle unprocess-last

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
	@echo "  eval-cycle  Pull, regenerate, evaluate, and send one live notification"
	@echo "  unprocess-last  Forget the last processed article so 'make run' re-sends it"
	@echo "  loop     Clear loop_output.md and run one loop.sh iteration"
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
product:
	python run_digest.py $(if $(FORCE),--force,)

# Evaluate the exact product written by the product target.
eval:
	python evaluate_digests.py

# Complete cycle. Evaluation failure stops the live notification step.
eval-cycle:
	git pull --ff-only
	$(MAKE) corpus
	$(MAKE) product FORCE=1
	$(MAKE) eval
	$(MAKE) unprocess-last
	$(MAKE) run

# Drop the most recently processed article so the next 'make run' re-scrapes,
# re-generates and re-sends its real notification (for eyeballing prompt changes).
unprocess-last:
	python -c "import json; p='processed_articles.json'; d=json.load(open(p)) if __import__('os').path.exists(p) else []; removed=d.pop() if d else None; json.dump(d, open(p, 'w')); print(f'Removed {removed}; next run will re-process it' if removed else 'Nothing to remove')"

# Run one loop iteration — clears previous output first
loop:
	> loop_output.md
	./loop.sh

# Remove Python cache artefacts (run_report.txt / full_prompt.txt / loop_output.md are kept for inspection)
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
