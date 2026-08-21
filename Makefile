.PHONY: help install lint test check run loop clean corpus product eval eval-cycle

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
	@echo "  eval-cycle  Run corpus -> product -> eval in order"
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

# Complete evaluation cycle. Non-zero exit means the product has failures.
eval-cycle: corpus
	$(MAKE) product
	$(MAKE) eval

# Run one loop iteration — clears previous output first
loop:
	> loop_output.md
	./loop.sh

# Remove Python cache artefacts (run_report.txt / full_prompt.txt / loop_output.md are kept for inspection)
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
