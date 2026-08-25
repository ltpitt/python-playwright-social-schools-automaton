# Social Schools Automaton — working notes

## NEVER COMMIT PERSONAL DATA

**This repository is public. It must never contain personal data — not in files, not in commit messages, not in test fixtures, not in git history.**

Personal data here means anything identifying a real person or flowing from the school account:

- Credentials of any kind: passwords, Pushbullet tokens, Gmail app passwords, LLM API keys
- Real email addresses, and the names of children, parents, teachers or classes/groups
- **Scraped Social Schools content** — article bodies, titles, attachments, digests, notification text. Real posts routinely name children, teachers and class compositions, so treat every scraped byte as personal data
- Anything derived from the above: run reports, event logs, corpus and evaluation snapshots, expectations, goal-loop candidates

Rules:

1. Everything of that kind lives under **`var/`**, which is gitignored in one line. Nothing personal belongs anywhere else in the tree.
2. **Never** `git add -A` / `git add .` in this repo. Stage files explicitly by name.
3. Tests, fixtures and examples use **invented** data only (`test@example.com`, "Test Article"). Never paste a real post into a test.
4. Before committing, verify staged content: `git diff --cached`.
5. If personal data does get committed, rewriting history is not enough for a pushed public repo — **rotate the exposed credentials** and tell the user immediately.

## What this is

A Python program that logs into Social Schools, finds new posts and their PDF/Word attachments, and delivers a short parent-actionable brief by Pushbullet and/or email.

Two first-class modes (see `CONTEXT.md`):

- **Digest** (default) — an LLM turns the post into a structured brief
- **Translation** (`DIGEST_ENABLED = false`) — Google Translate delivers the post directly, no LLM anywhere in the path

## Layout

```
socialschools/          The application
  __main__.py           CLI entry: python -m socialschools
  paths.py              Every file location, all under var/
  config.py             Config dataclass + cached get_config()
  logging_setup.py      configure_logging() — explicit, never on import
  console.py            Shared rich Console + theme + new_table()
  events.py             Canonical wide events (ADR 0008) + ambient event registry
  models.py             Article/Digest/Topic/Attachment/Recipient. Data only
  state.py              Which articles have already been delivered
  translate.py          Google Translate, cached
  pipeline.py           The run: log in, walk the feed, see each Article through
  scraping/             browser.py login.py feed.py attachments.py
  digest/               prompt.py+prompt.txt schema.py hints.py parse.py render.py generate.py
  llm/                  base.py copilot.py openai_compatible.py provider.py
  delivery/             recipients.py pushbullet.py gmail.py notify.py admin.py

tools/                  Dev-only harness, never shipped, run as python -m tools.X
  build_corpus.py       Snapshot real posts into var/corpus/
  run_digest.py         Replay the corpus through the real digest flow
  evaluate_digests.py   Score the product; structural + recall + faithfulness
  judge.py              Second opinion on a recall miss (ADR 0007)
  bakeoff.py            Compare models on quality vs real cost (ADR 0005)
  goal.py               Self-correcting prompt loop (ADR 0006)
  check_events.py       Did the last run get worse than the ones before it?

tests/                  conftest.py + one file per seam
docs/adr/               Architecture decision records
var/                    GITIGNORED. config.ini, state, logs, corpus, eval, goal
```

## Working effectively

```bash
make install-dev          # runtime + dev dependencies
cp config.example.ini var/config.ini   # then fill in credentials
make check                # lint + 312 tests + import sanity — the CI gate
make run                  # ARGS='--force -v' to pass flags through
```

Use `./.venv/bin/python` locally; the system Python lacks the dependencies.

`make check` is the gate and must stay green. Everything under `socialschools/`, `tools/` and `tests/` is linted, errors fatal and style advisory.

### Facts worth knowing

- **Playwright browsers are not installed.** `scraping/browser.py` resolves a system Chromium and falls back to Playwright's own. Nothing in the test suite drives a real browser.
- **`SOCIALSCHOOLS_VAR`** relocates the whole `var/` tree. `tests/conftest.py` uses it to sandbox the suite; nothing in the tests touches real data.
- **Logging is configured explicitly**, by `configure_logging()` in the entry point. Importing a module never opens a file handle.
- **The run report always gets DEBUG**, whatever `-v`/`-q`/`LOG_LEVEL` say. Quietening the terminal must never cost you evidence.
- **`--force` bypasses the seen-check for every article**, not just the newest — it notifies all recipients per article.
- **`digest/prompt.txt` is data, not code**, and `goal.py` rewrites it unattended. Never inline it back into a module (ADR 0006).
- Prompt placeholders are `<<LANGUAGE>>`, filled by `render_prompt()`, **not** `str.format` — the template is mostly JSON (ADR 0006).
- **Any non-digest LLM call must force `LLM_STRUCTURED_OUTPUT=False`**, or the provider pins the answer to `DIGEST_JSON_SCHEMA` and returns a digest-shaped stub. This has bitten twice.
- **Never log human text to the `"events"` logger** — it owns the JSONL and a prose line corrupts it. The narration logger is `"canonical"`.
- Escape scraped text with `rich.markup.escape` before printing it.
- `make bakeoff` and `make goal` **cost real money** and are never part of `make check`.

## Adding a feature

1. Write the test first, in the `tests/` file that matches the seam
2. Implement in the smallest module that can own it
3. `make check`
