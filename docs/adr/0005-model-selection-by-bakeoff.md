# Model choice is decided by measurement, not by reputation

Which model generates digests is settled by `make bakeoff`: the same corpus is replayed through each candidate, scored by the same evaluator, and reported as quality against real money. A candidate is a model plus optionally a reasoning effort (`google/gemini-2.5-flash@medium`), so "think harder with the cheap model" competes on equal terms with "buy a bigger model".

**Why:** the digests here are a selective-extraction task with negative constraints — carry every obligation, invent nothing, keep one event as one entry. Whether a cheap model is at its ceiling on that task is not something model marketing or general benchmarks can answer; a school newsletter in Dutch, with its attachments, is not MMLU. The corpus is a handful of posts a month, so the whole comparison costs cents and can be repeated whenever a candidate appears.

**How the score is made trustworthy enough to spend money on:**

- **Cases are split into `tune` and `holdout`** by a hash of the case id, so the split needs no bookkeeping file and never drifts. Expectations were written by looking at observed failures, so a score over the tuning cases is partly a score of hindsight. Only the holdout column is evidence that a change generalises.
- **Faithfulness is measured, not just recall.** `must_not_mention` phrases make a confident invention a violation. Recall alone rewards a model that says everything, and a time or obligation the message never gave is the most expensive mistake this system can make in a parent's calendar.
- **`--samples N` regenerates each case** so a difference between models can be told apart from run-to-run luck. Sampling is at `temperature 0`, which makes drift rare but not impossible, and a variant that is unstable at temperature 0 has told you something.
- **Cost comes from the provider, not a price list.** OpenRouter reports per-request cost when asked, so the bill in the report is what was actually charged for exactly this prompt and corpus.
- **Ranking is a graded score, not a pass rate.** The first full run scored 20/20 with 100% recall: a saturated gate, which would have reported every candidate as an equal and hidden the very answer the bakeoff exists to give. Ranking therefore uses recall minus 0.5 per violation and 0.05 per warning, so the advisory checks — where the remaining signal lives once nothing fails outright — still separate two models. The evaluator says so out loud when it detects saturation.

**Trade-off / consequences:**
- A bakeoff regenerates every case for every candidate and therefore costs real money and real time. It is a deliberate act, never part of `make check` or the eval cycle.
- The corpus is small (tens of posts), so the holdout is a handful of cases. It catches gross overfitting, not subtle differences. Treat a one-case gap, or a score gap under 0.02, as noise.
- Products, scorecards and expectations quote real posts and stay gitignored, so the numbers behind a model decision cannot be published with the repo — only the conclusion.
- Structured output (`response_format`) and reasoning effort are sent when configured and dropped automatically when an endpoint rejects them, so a bakeoff can include backends that support neither.
