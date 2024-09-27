[![CI](https://github.com/ltpitt/python-playwright-social-schools-automaton/workflows/CI/badge.svg)](https://github.com/ltpitt/python-playwright-social-schools-automaton/actions)
[![CodeQL](https://github.com/ltpitt/python-playwright-social-schools-automaton/workflows/CodeQL/badge.svg)](https://github.com/ltpitt/python-playwright-social-schools-automaton/actions?query=workflow%3ACodeQL)
[![GitHub Issues](https://img.shields.io/github/issues-raw/ltpitt/python-playwright-social-schools-automaton)](https://github.com/ltpitt/python-playwright-social-schools-automaton/issues)
[![Total Commits](https://img.shields.io/github/last-commit/ltpitt/python-playwright-social-schools-automaton)](https://github.com/ltpitt/python-playwright-social-schools-automaton/commits)
[![GitHub commit activity](https://img.shields.io/github/commit-activity/4w/ltpitt/python-playwright-social-schools-automaton?foo=bar)](https://github.com/ltpitt/python-playwright-social-schools-automaton/commits)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/ltpitt/python-playwright-social-schools-automaton/blob/master/LICENSE)
![Contributions welcome](https://img.shields.io/badge/contributions-welcome-orange.svg)

# Social Schools Automaton
> A Python script to automate downloading, translating, and notifying about new PDFs from the social school website!

## Why This Exists

Hey there, awesome parents! 🎉

I got tired of the daily grind of logging into the school website, hunting for new PDFs, downloading them, and then translating them. So, I decided to automate the whole process! Now, we can all sit back, relax, and let this script do the heavy lifting. 🚀

## How It Works

1. **Logs into the school website** using your credentials.
2. **Checks for new PDFs** in the feed.
3. **Downloads the PDFs** if they are new.
4. **Extracts text** from the PDFs.
5. **Translates the text** into Italian (or any language you prefer).
6. **Sends a Pushbullet notification** with the translated text.

## Prerequisites

- Python 3.x
- Playwright
- PyMuPDF
- Deep Translator
- Pushbullet

## How to Use

1. Clone this repo locally.
2. Install the required packages:
    ```bash
    pip install -r requirements.txt
    ```
3. Customize the configuration variables in the script:
    ```python
    SCRAPED_WEBSITE_USER = "<PUT_USERNAME_HERE>"
    SCRAPED_WEBSITE_PASSWORD = "<PUT_PASSWORD_HERE>"
    PUSHBULLET_API_KEY = "<PUT_PUSHBULLET_API_KEY_HERE>"
    TRANSLATION_LANGUAGE = "it"  # Use en, fr, it, etc.
    ```
4. Run the script:
    ```bash
    python script.py
    ```

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
