[![CI](https://github.com/ltpitt/python-playwright-social-schools-automaton/workflows/CI/badge.svg)](https://github.com/ltpitt/python-playwright-social-schools-automaton/actions)
[![CodeQL](https://github.com/ltpitt/python-playwright-social-schools-automaton/workflows/CodeQL/badge.svg)](https://github.com/ltpitt/python-playwright-social-schools-automaton/actions?query=workflow%3ACodeQL)
[![GitHub Issues](https://img.shields.io/github/issues-raw/ltpitt/python-playwright-social-schools-automaton)](https://github.com/ltpitt/python-playwright-social-schools-automaton/issues)
[![Total Commits](https://img.shields.io/github/last-commit/ltpitt/python-playwright-social-schools-automaton)](https://github.com/ltpitt/python-playwright-social-schools-automaton/commits)
[![GitHub commit activity](https://img.shields.io/github/commit-activity/4w/ltpitt/python-playwright-social-schools-automaton?foo=bar)](https://github.com/ltpitt/python-playwright-social-schools-automaton/commits)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/ltpitt/python-playwright-social-schools-automaton/blob/master/LICENSE)
![Contributions welcome](https://img.shields.io/badge/contributions-welcome-orange.svg)

# Social Schools Automaton
> A Python script to automate downloading, translating, and notifying about new content from the social school website!

## Notification modes

The tool supports two modes, both treated as first-class:

| Mode | Config | What you get | Requirements |
|---|---|---|---|
| **Digest** (default) | `DIGEST_ENABLED = true` | Structured brief: TL;DR, action items, key dates, attachment link | An LLM backend (see below) |
| **Translation** | `DIGEST_ENABLED = false` | Google-translated article title + body | None beyond Python deps |

Set `DIGEST_ENABLED = false` in `config.ini` if you don't have an LLM backend or prefer a simpler, cost-free setup. You'll still get every article translated and delivered to your phone. In Translation mode no LLM machinery is loaded at all.

### Choosing an LLM backend (Digest mode)

When `DIGEST_ENABLED = true`, pick a backend with `LLM_PROVIDER`:

| `LLM_PROVIDER` | Backend | Cost / privacy | Config needed |
|---|---|---|---|
| `copilot` (default) | GitHub Copilot CLI | Uses your Copilot plan; content goes to GitHub | Copilot CLI installed & authenticated |
| `openai_compatible` | Local **Ollama** (`http://localhost:11434/v1`) | **Free & fully local** — content never leaves your network | `LLM_BASE_URL`, `LLM_MODEL` |
| `openai_compatible` | **OpenRouter** / other cloud provider | Pay per use; content goes to that provider | `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` |

The `openai_compatible` provider works with any OpenAI-compatible `/chat/completions` endpoint (Ollama, OpenRouter, LM Studio, and most cloud providers), so one setting covers local, self-hosted, and cloud. See `config.example.ini` for ready-to-copy examples. Whichever backend you choose, the model is used as a pure text transformer with no tool access (see `docs/adr/0004-pluggable-llm-providers.md`).

### Is the cheap model good enough?

Don't guess — measure. `make bakeoff MODELS='model-a model-b@medium'` replays the same local corpus through each candidate, scores every digest the same way, and prints quality against the money actually charged:

```
variant                             holdout     tune  recall  viol  warn  unstable      cost  sec/case
google/gemini-2.5-flash               3/4      10/12     89%     1     6         0   $0.0121       2.4
google/gemini-2.5-flash@medium        4/4      11/12     94%     0     4         0   $0.0298       5.1
```

A candidate is `model` or `model@reasoning_effort`, so raising the thinking budget on a cheap model competes head-to-head with buying a bigger one — usually the cheaper upgrade. Judge on the **holdout** column: those cases were held back from prompt tuning, so they are the ones that say whether a change generalises. `make bakeoff` costs real money (every case is regenerated for every candidate) and is never part of `make check`. Method and its limits: `docs/adr/0005-model-selection-by-bakeoff.md`.

## Notify multiple people

Notifications are sent individually to each entry in `PUSHBULLET_API_KEYS`, a comma-separated list of `name:token` pairs — one per recipient, each using their own private Pushbullet access token:

1. Each recipient creates their own free [Pushbullet](https://www.pushbullet.com/) account (or uses their existing one) and installs the app on their phone.
2. Each recipient generates their own access token at [pushbullet.com/#settings/account](https://www.pushbullet.com/#settings/account).
3. Set `PUSHBULLET_API_KEYS` in `config.ini` (the name is only used in logs, so you can tell who a push went to):
   ```ini
   PUSHBULLET_API_KEYS = You:your_token_here,Partner:partners_token_here,Grandma:another_persons_token_here
   ```
4. The script pushes the same notification individually to every entry. Nobody needs access to anyone else's token, and only the people you explicitly list ever receive anything.

A single entry (e.g. `PUSHBULLET_API_KEYS = You:your_token_here`) keeps the original single-recipient behavior.

### Per-recipient language

Each recipient can receive notifications in their own language by appending `:language` to their entry:

```ini
PUSHBULLET_API_KEYS = Davide:davides_token:it,Daniela:danielas_token:en
```

A recipient without a `:language` suffix falls back to `TRANSLATION_LANGUAGE`. This works the same way for `EMAIL_RECIPIENTS` (see below). Content is generated **once per distinct language actually requested** — never per recipient — and shared by everyone who asked for that language, so nothing is translated (or summarized, in Digest mode) more than necessary.

> We deliberately don't use Pushbullet **channels** for this: channel subscriptions require no approval from the owner, and the `channel-info` API is publicly queryable without authentication — anyone who learns the channel tag can read/subscribe to notifications. Since these notifications can include your child's name, school, and schedule, per-recipient private tokens are the safer choice.

## Notify by email (Gmail)

Not everyone uses Pushbullet, so notifications can also (or instead) be sent by **email** via Gmail. Pushbullet and email are independent: configure either one, or both.

- Leave `PUSHBULLET_API_KEYS` empty to skip Pushbullet.
- Leave `EMAIL_RECIPIENTS` empty to skip email.

To enable email, set these in `config.ini`:

```ini
EMAIL_SENDER = your_gmail_address@gmail.com
EMAIL_APP_PASSWORD = your_gmail_app_password
EMAIL_RECIPIENTS = You:you@example.com,Partner:partner@example.com
```

- `EMAIL_SENDER` is the Gmail address the notifications are sent **from**.
- `EMAIL_APP_PASSWORD` is a Gmail **App Password**, *not* your normal Google password. Enable [2-Step Verification](https://myaccount.google.com/security), then create one at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
- `EMAIL_RECIPIENTS` mirrors `PUSHBULLET_API_KEYS`: a comma-separated list of `name:email` pairs (the name is only used in logs). Each recipient is emailed individually, so their address is never exposed to the others. A single entry works too.
- Like `PUSHBULLET_API_KEYS`, each entry accepts an optional `:language` suffix (e.g. `You:you@example.com:it`) to override `TRANSLATION_LANGUAGE` for that recipient — see [Per-recipient language](#per-recipient-language) above.

Sending assumes Gmail's SMTP server (`smtp.gmail.com`).

## Admin alerts

Parents only ever see the good stuff. Everything that goes *wrong* — a failed login, an article whose body can't be read, an attachment that won't download, a degraded digest, a broken state file, a fatal crash — is sent to a separate **admin channel** so you can spot problems without reading the logs.

Both settings are optional and independent; leave both empty to disable admin alerting.

```ini
ADMIN_PUSHBULLET_API_KEY = o.your_admin_pushbullet_token
ADMIN_EMAIL = admin@example.com
```

- `ADMIN_PUSHBULLET_API_KEY` is a single Pushbullet access token (no `name:` prefix).
- `ADMIN_EMAIL` is a single address, delivered using the `EMAIL_SENDER` / `EMAIL_APP_PASSWORD` credentials above.
- Admin delivery is best-effort: if the admin channel itself is down, the run continues and the failure is only logged.

### When is an article marked as processed?

An article is recorded in `processed_articles.json` **only when it was fully processed and every notification was delivered**. If the digest fails, a notification fails to send, or the article body can't be read, the article stays unmarked and is retried on the next run.

Two degraded-but-delivered cases still count as processed, because the notification did reach parents (and it tells them something was missing) — re-sending it every run would just be spam:

- an attachment that could not be downloaded or read (the notification carries a "could not be read" warning)
- a digest that fell back to placeholder text after the LLM returned invalid output twice

Both still raise an admin alert.


## Why this exists

Hey there, awesome parents! 🎉

I got tired of the daily grind of logging into the school website, hunting for new PDFs and Word documents, downloading them, and then translating them. So, I decided to automate the whole process!  
Now, we can all sit back, relax, and let this script connect to the school website, get the article and its Word or PDF file, do the translation if you want, and send a pushbullet (you'll need this app) notification on your phone. 🚀

## How does it work

1. **Logs into the school website** using your credentials.
2. **Checks for new content** in the feed (both PDFs and Word documents).
3. **Downloads any new files** (PDFs and Word documents).
4. **Extracts text** from the files.
5. **Builds a Digest** (or a plain translation, see [Notification modes](#notification-modes) above) in your preferred language (default is English), including the post's original date and time.
6. **Sends Pushbullet notifications** with the result.
7. **Remembers which articles it has already processed**, so you never get duplicate notifications.

## Prerequisites

- Python 3.x
- Playwright (for web automation)
- PyMuPDF (for PDF handling)
- python-docx (for Word document handling)
- Deep Translator (for translations)
- Pushbullet (for notifications)

## How to use

1. Clone this repo locally.
2. Install the required packages:
    ```bash
    pip install -r requirements.txt
    ```
3. Set up your configuration:
   - Copy the example configuration file:
     ```bash
     cp config.example.ini config.ini
     ```
   - Open `config.ini` in your favorite text editor
   - Fill in your details:
     ```ini
     [DEFAULT]
     SCRAPED_WEBSITE_USER = your.email@example.com   # Your Social Schools login email
     SCRAPED_WEBSITE_PASSWORD = your_password        # Your Social Schools password
     PUSHBULLET_API_KEYS = You:your_pushbullet_key   # Comma-separated 'name:token' pairs (leave empty to use email only)
     EMAIL_SENDER =                                  # Gmail address to send from (optional, see "Notify by email")
     EMAIL_APP_PASSWORD =                            # Gmail App Password (optional)
     EMAIL_RECIPIENTS =                              # Comma-separated 'name:email' pairs (optional)
     ADMIN_PUSHBULLET_API_KEY =                      # Admin-only token for error alerts (optional)
     ADMIN_EMAIL =                                   # Admin-only address for error alerts (optional)
     TRANSLATION_LANGUAGE = en                       # "en" for English, "it" for Italian, etc.
     DIGEST_ENABLED = true                           # false for plain translation mode
     ```
   - Save the file

4. Run the script:
    ```bash
    python get_social_schools_news.py
    ```

## Running it on a schedule

The script checks for new content once per run, so schedule it (e.g. hourly) with cron. Since `config.ini` and `processed_articles.json` are read relative to the current directory, `cd` into the repo before invoking the venv's Python:

```cron
0 * * * * cd "/path/to/python-playwright-social-schools-automaton" && "/path/to/python-playwright-social-schools-automaton/.venv/bin/python" "/path/to/python-playwright-social-schools-automaton/get_social_schools_news.py" >> "/path/to/python-playwright-social-schools-automaton/cron.log" 2>&1
```

## Important notes

- Keep your `config.ini` file safe and never share it with others
- The script will remember which articles it has already processed, but only once they are fully processed and notified — see [Admin alerts](#admin-alerts)
- You'll get notifications on your phone through Pushbullet when new content is available
- Both PDFs and Word documents are supported and will be processed automatically

## Meta

Davide Nastri – [d.nastri@gmail.com](mailto:d.nastri@gmail.com)

Distributed under the MIT license. See ``LICENSE`` for more information.

Social Schools Automaton

## Contributing

1. Fork it (<https://github.com/ltpitt/python-playwright-social-schools-automaton/fork>)
2. Create your feature branch (`git checkout -b feature/fooBar`)
3. Commit your changes (`git commit -am 'Add some fooBar'`)
4. Push to the branch (`git push origin feature/fooBar`)
5. Create a new Pull Request
