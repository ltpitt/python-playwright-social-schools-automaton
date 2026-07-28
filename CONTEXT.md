# Social Schools Automaton

Turns Dutch school-newsletter posts (and their attachments) into a short, parent-actionable brief in the reader's language, delivered as a notification.

## Product Principles

**Both operating modes are first-class citizens.**
Not every parent has access to an LLM. Cost, privacy concerns, or simply preferring a simpler setup are all valid reasons to run without one. The tool must provide a decent, useful experience in both modes — parity of features is not the goal, but parity of care is.

- **Digest mode** (default): uses the Copilot CLI to produce a structured, actionable brief. Requires GitHub Copilot access.
- **Translation mode** (`DIGEST_ENABLED = false`): uses Google Translate to deliver the article directly. Free, zero external dependencies beyond the translation library, and always available.

Neither mode should send raw scraped content. Translation mode sends the Google-translated article body — that is its intended, first-class output, not a fallback or degraded path.

## Language

**Article**:
A single post in the Social Schools feed, consisting of a title, a body, and zero or more attachments.
_Avoid_: Post, news item, message

**Attachment**:
A PDF or Word document linked from an Article.
_Avoid_: File, document, enclosure

**Digest**:
The structured, parent-facing output produced for one Article in Digest mode, in the reader's language, delivered as a single notification. Shape: translated title, a 1–3 sentence TL;DR, Action Items (or "No action needed"), optional Key Dates, and a reference back to any Attachment. Replaces the raw text entirely — the raw Article body and extracted Attachment text are model *input*, never delivered.
_Avoid_: Summary, report, notification body

**Translation**:
The parent-facing output produced for one Article in Translation mode. The Article title and body are translated directly via Google Translate and delivered as a notification. Simple, free, and intentional — not a degraded Digest.
_Avoid_: Fallback, raw text, emergency output

**Action Item**:
A concrete thing the reading parent must do because of an Article — with its deadline/date where one exists (e.g. "sign the trip form by Fri", "pay €12.50", "bring gym kit Tue").
_Avoid_: Task, todo, reminder
