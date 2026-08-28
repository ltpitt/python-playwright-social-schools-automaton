# The self-correcting loop may write one inert file

`goal.py` closes the loop the evaluator was always missing: regenerate the corpus, score it, feed the failures back to a model, rewrite the prompt, measure again. Left there, it would be an agent with a budget and an opinion about a codebase. It is instead an agent with a budget and write access to exactly one file — `digest_prompt.txt`, which holds the Digest prompt template and nothing else.

**Why the prompt moved out of `get_social_schools_news.py`:** the template used to be a string literal in the middle of a module that also holds login, Playwright, Pushbullet credentials and config parsing. Pointing an unattended rewriter at that file makes every one of those things reachable by a bad turn. One file, one string, one responsibility means a wrong answer is a wrong prompt.

**Why it is a `.txt` and not a `.py`:** the text the loop rewrites toward is shaped by failing cases, and those cases quote Article and Attachment content scraped from the school website — untrusted input, per ADR 0002. Had the loop written a Python module, a poisoned attachment that talked a model into emitting an import statement would execute on the next `make product`. ADR 0002 promises that the worst case of a poisoned attachment is a poor-quality Digest; that promise only survives if what the loop writes cannot execute. `digest_prompt.py` is a loader the loop never touches; `digest_prompt.txt` is data.

**Why it cannot touch the evaluator:** the loop is scored by `evaluate_digests.py` against `expectations.json`. An agent that can edit its own success criteria will eventually notice that deleting an expectation is cheaper than satisfying it. No instruction reliably prevents this, and file scope does. The gate is off the map, so the only path to a passing score is a better prompt.

**Why placeholders are `<<NAME>>` and not `{name}`:** the template is mostly a JSON example, so `str.format` required every literal brace to be doubled. The first real run showed what that costs: asked to rewrite a JSON document while preserving deliberately wrong-looking braces and five `{placeholder}` tokens, the model wrote natural JSON and substituted the placeholder values — the answer was rejected and the turn was lost to an artefact of our own serialisation choice. `<<NAME>>` collides with nothing in JSON or Dutch, so the model has nothing unnatural to preserve, and the file is easier for a human to read too.

**How a turn is spent:**

- **The improver call is tool-free**, exactly like the Digest call. Prompt in, replacement template out; `goal.py` performs the write, never the model.
- **A candidate is validated before it costs anything**: every placeholder present, no invented ones, and one render with dummy values. A truncated or mangled answer is caught in a millisecond instead of after a full corpus regeneration.
- **A malformed answer gets one repair attempt**, shown exactly what was wrong. Only then is the turn spent, and the rejected text is kept in `goal_output/` so the failure can be read rather than guessed at.
- **Progress is measured on the holdout split.** Expectations were written by staring at failures, so tuning-set movement is partly hindsight. Tune climbing while holdout stands still is overfitting, and the ledger shows it happening.
- **The best turn is restored, not the last.** A loop that ends on its worst attempt is worse than not running one.

**Stop conditions**, in the order they fire: every holdout case passes; the turn budget runs out; or `--patience` consecutive turns fail to beat the best result so far — the "same command, same output, third time" signal.

**Trade-off / consequences:**
- Every turn regenerates every case, so a run costs real money and real time. `make goal` is a deliberate act, never part of `make check` or `make eval-cycle`.
- The loop can only improve what prompt wording can improve. A failure caused by attachment extraction, scraping or rendering will stall it, and stalling is the honest answer rather than a prompt bloated with rules that cannot help.
- Nothing is committed. `digest_prompt.txt` is left dirty in the working tree for review, and `git checkout digest_prompt.txt` discards the run.
- The ledger and the candidate archive quote real posts and are gitignored, so the evidence behind a prompt change cannot be published with the repo — only the prompt.
- The prompt is now loaded from disk at import. A missing or unreadable `digest_prompt.txt` is a hard startup failure rather than a silently degraded Digest, which is the right way round.
- `run_digest.py` and `evaluate_digests.py` are invoked directly rather than through `make`, because a failing gate is the expected case here and `make` decorates an expected non-zero exit with an alarming error banner.
