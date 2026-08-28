"""Development-only harness: corpus, evaluation, judge, bakeoff, goal loop, health.

None of this ships to the Raspberry Pi and none of it is imported by the
application. Everything it writes is derived from real posts and therefore
personal data, so it all goes under `var/` (see `socialschools.paths`).

Run as modules from the repository root: `python -m tools.run_digest`.
"""
