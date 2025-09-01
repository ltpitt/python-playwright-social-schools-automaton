# Social Schools Automaton - GitHub Copilot Instructions

Always reference these instructions first and fallback to search or bash commands only when you encounter unexpected information that does not match the info here.

## About the Project
Social Schools Automaton is a Python automation script that uses Playwright for web scraping. It automates downloading, translating, and notifying about new content from the Social Schools website. The script:
- Logs into Social Schools using provided credentials
- Scrapes articles and checks for new content
- Downloads PDFs and Word documents automatically
- Translates content using Google Translator
- Sends notifications via Pushbullet when new content is found

## Working Effectively

### Bootstrap and Setup
Run these commands in sequence to set up the development environment:

```bash
# Install Python dependencies - takes 45 seconds on first run, 1-3 seconds when cached
pip install -r requirements.txt

# Create configuration file from template
cp config.example.ini config.ini
# Edit config.ini with your credentials (see Configuration section below)
```

**CRITICAL PLAYWRIGHT SETUP**: The standard `playwright install` fails due to browser download issues. The application is configured to use the system browser at `/usr/bin/chromium-browser` via the `executable_path` parameter in the code.

### Configuration Requirements
**CRITICAL**: The application requires real credentials to function. Edit `config.ini`:

```ini
[DEFAULT]
SCRAPED_WEBSITE_USER = your.email@socialschools.com    # Your Social Schools login
SCRAPED_WEBSITE_PASSWORD = your_password               # Your Social Schools password  
PUSHBULLET_API_KEY = your_pushbullet_api_key          # Get from Pushbullet settings
TRANSLATION_LANGUAGE = en                              # "en" for English, "it" for Italian, etc.
```

**NEVER** commit real credentials to the repository. Keep `config.ini` in `.gitignore`.

### Build and Test Commands

```bash
# NEVER CANCEL: Lint the code - completes in <1 second
flake8 get_social_schools_news.py --count --select=E9,F63,F7,F82 --show-source --statistics
flake8 get_social_schools_news.py --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics

# NEVER CANCEL: Run all tests - completes in <1 second, timeout 30 seconds
pytest -v

# Test script imports correctly
python -c "import get_social_schools_news; print('Script imports successfully')"
```

### Running the Application

```bash
# Run the main script (requires valid credentials in config.ini)
# No special environment variables needed - system browser is used automatically
python get_social_schools_news.py
```

## Validation

### Pre-Commit Validation Steps
ALWAYS run these before committing changes:

1. **Lint the code**: `flake8 get_social_schools_news.py --count --select=E9,F63,F7,F82 --show-source --statistics`
2. **Run full test suite**: `pytest -v` 
3. **Test script import**: `python -c "import get_social_schools_news; print('Script imports successfully')"`

### Manual Testing Scenarios
Since the application requires real credentials for Social Schools, full end-to-end testing should validate:

1. **Configuration loading**: Script can read config.ini without errors
2. **Playwright setup**: Browser launches with system browser automatically
3. **Import validation**: All dependencies import correctly
4. **Component testing**: Use the test suite to validate individual functions

**Testing Playwright functionality**:
```python
# Create test script to validate Playwright works
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True, 
        executable_path='/usr/bin/chromium-browser'
    )
    page = browser.new_page()
    page.goto("data:text/html,<h1>Test</h1>")
    print(page.text_content('h1'))  # Should print "Test"
    browser.close()
```

**DO NOT** run the full script without proper Social Schools credentials as it will fail at login.

### Known Working Test Commands
The test suite covers all major components and runs successfully:
- `test_load_processed_articles` - JSON file handling
- `test_save_processed_article` - Article tracking 
- `test_translate` - Google Translator integration
- `test_send_notification` - Pushbullet notifications
- `test_process_article_content` - Content processing pipeline

## Important Technical Details

### Playwright Browser Issue
**CRITICAL ISSUE**: `playwright install` fails due to browser download problems. 

**SOLUTION**: The application has been updated to use the system Chromium browser at `/usr/bin/chromium-browser` via the `executable_path` parameter in the `run()` function. No manual setup or environment variables needed.

### Dependencies and Timing
- **Python**: Requires 3.10+ (tested on 3.10, 3.11, 3.12.3)
- **pip install**: ~45 seconds first time, ~1-3 seconds when packages cached. NEVER CANCEL - timeout 120 seconds
- **pytest**: All 11 tests complete in <1 second. NEVER CANCEL - timeout 30 seconds  
- **flake8**: Linting completes in <1 second. NEVER CANCEL - timeout 30 seconds

### Code Quality Issues
The current codebase has some flake8 violations that should be addressed:
- Unused imports (typing.Optional, shutil)
- Line length violations (>127 characters)
- Whitespace and blank line formatting issues
- Unused variables

Always run both flake8 commands to catch these issues.

## Common Development Tasks

### Adding New Features
1. Write tests first in `test_get_social_schools_news.py`
2. Implement feature in `get_social_schools_news.py`
3. Run `pytest -v` to validate tests pass
4. Run `flake8` to check code style
5. Test import: `python -c "import get_social_schools_news"`

### Debugging Issues
1. Check configuration file exists and has valid format
2. Verify Playwright environment variable is set
3. Run individual test functions to isolate problems
4. Check that all dependencies are installed

### CI Pipeline Expectations
The GitHub Actions CI pipeline runs:
1. Python 3.10 and 3.11 matrix
2. `pip install -r requirements.txt`
3. `playwright install` (fails but CI handles it)
4. `flake8` linting (expects no E9,F63,F7,F82 errors)
5. `pytest` tests (expects all 11 tests to pass)

## File Structure Reference

### Repository Root
```
.
├── .github/
│   ├── workflows/
│   │   ├── CI.yml              # GitHub Actions pipeline
│   │   └── CodeQL.yml          # Security scanning
│   └── copilot-instructions.md # This file
├── .gitignore                  # Standard Python gitignore
├── LICENSE                     # MIT license
├── README.md                   # User documentation  
├── config.example.ini          # Configuration template
├── config.ini                  # Your credentials (git-ignored)
├── get_social_schools_news.py  # Main application script
├── requirements.txt            # Python dependencies
└── test_get_social_schools_news.py # Test suite
```

### Key Files to Know
- **`get_social_schools_news.py`**: Main script - contains all automation logic
- **`test_get_social_schools_news.py`**: Comprehensive test suite with 11 tests
- **`requirements.txt`**: All Python dependencies with pinned versions
- **`config.example.ini`**: Template for configuration (copy to config.ini)
- **`.github/workflows/CI.yml`**: CI pipeline that runs on every push/PR

## Troubleshooting

### Common Issues
1. **"Executable doesn't exist at .../headless_shell"**: This is expected - the application uses system browser automatically
2. **"No module named 'config'"**: Create `config.ini` from `config.example.ini`
3. **Login failures**: Verify credentials in config.ini are correct
4. **Import errors**: Run `pip install -r requirements.txt`
5. **Test failures**: Check that config.ini exists (tests mock it automatically)

### Emergency Reset
If the environment gets corrupted:
```bash
rm -rf __pycache__ .pytest_cache
pip uninstall -y -r requirements.txt
pip install -r requirements.txt
# No special Playwright setup needed - system browser is used automatically
```