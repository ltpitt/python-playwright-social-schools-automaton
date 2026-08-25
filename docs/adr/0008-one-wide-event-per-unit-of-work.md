# One wide event per unit of work, carrying shapes and never content

Every run and every Article now writes exactly one line to `events.jsonl`: a flat structured record carrying everything known about that unit of work by the time it ended — what code was running, what configuration, how many attachments, how the digest was shaped, how long it took, what it cost, and whether it worked. `run_report.txt` remains, but as narration rather than evidence.

**Why this and not more logging.** A deterministic line of the notification template stopped appearing in real notifications, and nothing in the system could say when it stopped, whether it had been sent, or what else changed at the same time. The logs held the answer in principle — and were truncated on every run, unsearchable across runs, and organised as prose. More prose would not have helped. What was missing was a record of the *shape* of each thing produced, kept long enough to compare.

The canonical-log-line pattern answers exactly that: initialise an empty record when the work starts, add to it as the work proceeds, emit it once at the end, including when it throws. One event per unit of work, wide rather than deep. `check_events.py` then reads them back and reports what changed for the worse — `has_footer` was true in 100% of the last ten articles and is false now — alongside what changed about the run, because `prompt_sha` moving in the same run is the first thing worth suspecting.

**Shapes, never content.** The usual advice is to throw everything into the blob on the grounds that a field you skipped is a question you cannot ask. That advice assumes the blob is not made of children's names. Events here record `title_sha8`, `body_chars`, `topics=2`, `has_footer=true` — enough to detect that something changed, never enough to reconstruct what a post said. The text stays in the rotated debug log, joined by `run_id` when it genuinely matters. This is the one place this project departs from the pattern as usually described, and it departs on purpose.

**Consequences and trade-offs:**

- **`events.jsonl` is the source of truth; the log is the story.** Aggregation is one-way — a count of failures cannot be turned back into a reason, but raw events can always be counted. So events are stored unaggregated and rotated, not summarised.
- **Telemetry may never break the work.** `emit()` catches everything, and serialisation falls back to `str` rather than dropping an event over one awkward value. A run that fails because its event could not be written would be a strictly worse system.
- **No sampling.** The pattern calls for it at scale; this processes about one Article per run. Keeping everything is affordable here and strictly more useful.
- **No OpenTelemetry.** For a single-user job on a Raspberry Pi, an SDK and a backend are more moving parts than the thing they observe. Wide events plus `jq` cover it, and map onto a real backend later without rework.
- **`run_report.txt` rotates rather than truncates.** It used to be opened `mode='w'` at import, so every run — and every subprocess, of which `goal.py` spawns several — wiped it. The evidence was always gone by the time anyone wanted it.
- **Every log line carries the run id**, so a canonical event and the narration behind it can be brought back together.
- **Events and their rotated backups are gitignored.** Shapes are not content, but article ids and the rhythm of one family's week are still theirs.
- **`make health` is part of `eval-cycle`.** The corpus eval judges digests the model just generated from stored inputs; health judges what production actually sent. They fail in different ways, so both run, and neither hides the other.
