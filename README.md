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
| **Digest** (default) | `DIGEST_ENABLED = true` | Structured brief: TL;DR, action items, key dates, attachment link | GitHub Copilot CLI |
| **Translation** | `DIGEST_ENABLED = false` | Google-translated article title + body | None beyond Python deps |

Set `DIGEST_ENABLED = false` in `config.ini` if you don't have Copilot access or prefer a simpler, cost-free setup. You'll still get every article translated and delivered to your phone.

## Notify multiple people

By default, notifications go only to the devices logged into the Pushbullet account that owns `PUSHBULLET_API_KEY`. To also notify a partner (or anyone else) privately, give each of them their own Pushbullet access token:

1. Each recipient creates their own free [Pushbullet](https://www.pushbullet.com/) account (or uses their existing one) and installs the app on their phone.
2. Each recipient generates their own access token at [pushbullet.com/#settings/account](https://www.pushbullet.com/#settings/account).
3. Add those tokens to `config.ini` as `PUSHBULLET_EXTRA_API_KEYS`, as comma-separated `name:token` pairs (the name is only used in logs, so you can tell who a push went to):
   ```ini
   PUSHBULLET_EXTRA_API_KEYS = Partner:partners_token_here,Grandma:another_persons_token_here
   ```
4. The script pushes the same notification individually to your key and every extra key. Nobody needs access to anyone else's token, and only the people you explicitly list ever receive anything. Optionally set `PUSHBULLET_API_KEY_OWNER = YourName` to label your own key in logs too (defaults to "primary").

Leave `PUSHBULLET_EXTRA_API_KEYS` empty to keep the original single-recipient behavior.

> We deliberately don't use Pushbullet **channels** for this: channel subscriptions require no approval from the owner, and the `channel-info` API is publicly queryable without authentication — anyone who learns the channel tag can read/subscribe to notifications. Since these notifications can include your child's name, school, and schedule, per-recipient private tokens are the safer choice.


## Why this exists

Hey there, awesome parents! 🎉

I got tired of the daily grind of logging into the school website, hunting for new PDFs and Word documents, downloading them, and then translating them. So, I decided to automate the whole process!  
Now, we can all sit back, relax, and let this script connect to the school website, get the article and its Word or PDF file, do the translation if you want, and send a pushbullet (you'll need this app) notification on your phone. 🚀

## How does it work

1. **Logs into the school website** using your credentials.
2. **Checks for new content** in the feed (both PDFs and Word documents).
3. **Downloads any new files** (PDFs and Word documents).
4. **Extracts text** from the files.
5. **Translates the text** into your preferred language (default is Italian).
6. **Sends Pushbullet notifications** with both the original and translated text.
7. **Saves the content** in both original and translated formats.

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
     cp config.example.py config.py
     ```
   - Open `config.py` in your favorite text editor
   - Fill in your details:
     ```python
     SCRAPED_WEBSITE_USER = "your.email@example.com"  # Your Social Schools login email
     SCRAPED_WEBSITE_PASSWORD = "your_password"       # Your Social Schools password
     PUSHBULLET_API_KEY = "your_pushbullet_key"       # Get this from Pushbullet settings
     TRANSLATION_LANGUAGE = "it"                      # Use "en" for English, "it" for Italian, etc.
     ```
   - Save the file

4. Run the script:
    ```bash
    python get_social_schools_news.py
    ```

## Important notes

- Keep your `config.py` file safe and never share it with others
- The script will remember which articles it has already processed
- You'll get notifications on your phone through Pushbullet when new content is available
- The script will pause at certain points for you to check the content before proceeding
- Both PDFs and Word documents are supported and will be processed automatically
- All content is saved in both original and translated formats

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
