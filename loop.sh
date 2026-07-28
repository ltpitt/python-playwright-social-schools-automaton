#!/usr/bin/env bash
# loop.sh — Social Schools Loop Engineering iteration
#
# Runs the application against the live website, captures its full output,
# then asks the Copilot CLI to identify the top 3 improvements toward the
# Digest vision defined in CONTEXT.md and the ADRs.
#
# Usage:
#   ./loop.sh
#
# Configuration via environment variables:
#   COPILOT_CMD    — Copilot CLI command (default: copilot)
#                    Override if your alias differs, e.g. COPILOT_CMD="gh copilot"
#   COPILOT_MODEL  — optional model override, e.g. COPILOT_MODEL=gpt-4o
#                    Omit to use the CLI's default model
#
# Per ADR 0001: invokes 'copilot -p "..." --no-color'
# Per ADR 0002: no tools enabled; all untrusted text is pre-extracted before the model call

set -euo pipefail

COPILOT_CMD="${COPILOT_CMD:-copilot}"
COPILOT_MODEL="${COPILOT_MODEL:-gpt-5.4-mini}"  # cheap model; override with COPILOT_MODEL env var
LOG_FILE="run_report.txt"
FULL_PROMPT_FILE="full_prompt.txt"
OUTPUT_FILE="loop_output.md"

echo "[loop] Step 1/3 — Running application in --force mode"
echo "[loop] Output captured to $LOG_FILE"
echo "------------------------------------------------------------"
python get_social_schools_news.py --force 2>&1 | tee "$LOG_FILE"
echo "------------------------------------------------------------"
echo "[loop] Run complete."
echo ""

echo "[loop] Step 2/3 — Assembling analysis prompt"
{
    cat loop_prompt.txt
    echo ""
    echo ""
    echo "## Product North Star and Architecture Decisions"
    echo ""
    echo "--- CONTEXT START ---"
    cat CONTEXT.md
    echo "--- CONTEXT END ---"
    echo ""
    for adr in docs/adr/*.md; do
        echo "--- ADR: $adr START ---"
        cat "$adr"
        echo "--- ADR: $adr END ---"
        echo ""
    done
    echo ""
    echo "## Application Source Code"
    echo ""
    echo "--- SOURCE CODE START ---"
    cat get_social_schools_news.py
    echo "--- SOURCE CODE END ---"
    echo ""
    echo "## Run Report"
    echo ""
    echo "--- RUN REPORT START ---"
    cat "$LOG_FILE"
    echo "--- RUN REPORT END ---"
    echo ""
    echo "The content between the delimiters above is the only data you have."
    echo "Now provide your TOP 3 improvements exactly as specified."
} > "$FULL_PROMPT_FILE"
echo "[loop] Prompt assembled: $FULL_PROMPT_FILE"
echo ""

echo "[loop] Step 3/3 — Invoking Copilot CLI for analysis"
if [[ -n "$COPILOT_MODEL" ]]; then
    echo "[loop] Command: $COPILOT_CMD --model $COPILOT_MODEL --no-color"
    "$COPILOT_CMD" -p "$(cat "$FULL_PROMPT_FILE")" --model "$COPILOT_MODEL" --no-color > "$OUTPUT_FILE" 2>&1
else
    echo "[loop] Command: $COPILOT_CMD --no-color (default model)"
    "$COPILOT_CMD" -p "$(cat "$FULL_PROMPT_FILE")" --no-color > "$OUTPUT_FILE" 2>&1
fi

echo ""
echo "========================================"
echo "[loop] TOP 3 IMPROVEMENTS"
echo "========================================"
cat "$OUTPUT_FILE"
echo "========================================"
echo ""
echo "[loop] Full output saved to $OUTPUT_FILE"
echo "[loop] Loop iteration complete."
