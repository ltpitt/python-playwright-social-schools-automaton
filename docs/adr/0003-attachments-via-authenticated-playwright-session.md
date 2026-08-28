# Attachments downloaded via authenticated Playwright session

PDF and Word document attachments are downloaded using the same authenticated Playwright browser session (`context.request.get(url)`) rather than making separate unauthenticated HTTP requests.

**Why:** Attachment URLs are CloudFront signed URLs scoped to the authenticated user session. Plain `requests.get` calls (even with the raw signed URL) return 403 because CloudFront validates the request against the session cookies carried by the browser. Reusing the Playwright `APIRequestContext` inherits those cookies at no extra cost, and avoids the complexity of extracting and replaying them manually.

**Consequences:**
- The browser context must remain open for the full duration of article processing (including attachment download). Closing it before downloads complete would break authentication.
- `_download_pdf` and `_download_docx` accept an optional `browser_context=None` parameter and fall back to plain `requests` when no context is provided. This preserves the legacy `download_pdf` path and makes the functions testable without a live browser.
- Attachment failures (403s, network errors, extraction errors) are fail-closed: the `Attachment` object is retained in the manifest with `failed=True` so the rendered Digest can reference it with a warning rather than silently drop provenance.

**Update (2026-08-25):** the decision stands; the code moved. `_download_pdf` and `_download_docx` were one function twice, and are now `socialschools.scraping.attachments.download_attachment(url, output_path, browser_context=None)`. The pycurl-based `download_pdf` mentioned above had no callers left and was deleted with its dependency — the `requests` fallback is what keeps the function testable without a live browser.
