[![CI](https://github.com/ltpitt/python-playwright-social-schools-automaton/workflows/CI/badge.svg)](https://github.com/ltpitt/python-playwright-social-schools-automaton/actions)
[![CodeQL](https://github.com/ltpitt/python-playwright-social-schools-automaton/workflows/CodeQL/badge.svg)](https://github.com/ltpitt/python-playwright-social-schools-automaton/actions?query=workflow%3ACodeQL)
[![GitHub Issues](https://img.shields.io/github/issues-raw/ltpitt/python-playwright-social-schools-automaton)](https://github.com/ltpitt/python-playwright-social-schools-automaton/issues)
[![Total Commits](https://img.shields.io/github/last-commit/ltpitt/python-playwright-social-schools-automaton)](https://github.com/ltpitt/python-playwright-social-schools-automaton/commits)
[![GitHub commit activity](https://img.shields.io/github/commit-activity/4w/ltpitt/python-playwright-social-schools-automaton?foo=bar)](https://github.com/ltpitt/python-playwright-social-schools-automaton/commits)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/ltpitt/python-playwright-social-schools-automaton/blob/master/LICENSE)
![Contributions welcome](https://img.shields.io/badge/contributions-welcome-orange.svg)

# Social Schools Automaton
> A Python script to automate downloading, translating, and notifying about new content from the social school website!

## Why this exists

Hey there, awesome parents! 🎉

I got tired of the daily grind of logging into the school website, hunting for new PDFs and Word documents, downloading them, and then translating them. So, I decided to automate the whole process! Now, we can all sit back, relax, and let this script do the heavy lifting. 🚀

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
