---
name: second-opinion
description: Get an independent review of the current change from a different model family (Gemini via the Antigravity CLI) using a review packet in .ai/review/. Use for high-risk changes - payments, auth, finance logic, migrations, concurrency - or when stuck.
argument-hint: "[what to review, e.g. 'current diff' or 'design for T-012']"
disable-model-invocation: true
---

Review target: $ARGUMENTS

A second model from a different family catches blind spots the first one shares with itself. Gemini reviews; it never edits source.

1. **Build the packet** — write `.ai/review/<YYYY-MM-DD>-<slug>.md` containing:
   - Goal and task id; what behaviour must change and what must not
   - The diff (`git diff` or the relevant range), or the design under review
   - Paths of the docs to read: `.ai/rules.md`, relevant `.ai/context/flows/*.md`, `.ai/lld.md` sections
   - 3–6 specific questions (edge cases, concurrency, money/rounding, security, migrations, tests missing)
   - Required output format: findings as `severity (high/med/low) · file:line · problem · suggested fix`, then "Missing tests", then "Questions"
2. **Run Gemini if possible** — check `command -v agy`. If present, run `agy --help` and look for a non-interactive / prompt flag. Only if one exists, run it from the repo root with this prompt:
   `Read <packet path> and every file it references. Do not modify any files. Write your findings to <packet path without .md>-gemini.md in the requested format.`
   Do not guess flags. If `agy` is missing, has no non-interactive mode, or returns a quota/limit error, go to step 3.
3. **Hand-off** — give the human the exact prompt above and tell them to run it in `agy` (or the Gemini app with the packet attached) from the repo, then reply when the findings file exists.
4. **Triage** — when findings arrive, answer each one: agree (fix it via the normal task loop) or disagree (one-line reason). Never apply Gemini's suggestions blindly. Log notable outcomes in `.ai/memory/decisions.md`.

Never put secrets or `.env` values in the packet.
