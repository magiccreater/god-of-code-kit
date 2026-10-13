# Rule book (read first, every session)

This is the operating manual for any AI agent working in this repo (Claude Code, Antigravity/Gemini, others).
Project-specific facts live in the other files under `.ai/`. Keep this file under ~150 lines.
Section 0 belongs to this project. Sections 1–9 are maintained by the God of Code kit (re-running its
installer updates them); put project-specific rules in section 0 or below the kit block.

## 0. Project commands and project rules (fill in during onboarding)

| Action | Command |
|---|---|
| Install deps | `TODO` |
| Run app locally | `TODO` |
| Unit tests (quiet, fail-fast) | `TODO` |
| Single test | `TODO` |
| Lint / format | `TODO` |
| Type check / static analysis | `TODO` |
| Build | `TODO` |

<!-- god-of-code:core:begin -->
## 1. Session start protocol

1. Read `.ai/memory/state.md` (working memory), `.ai/tasks.md` (In progress / Blocked), `.ai/memory/questions.md` (open questions).
2. If `state.md` disagrees with the code or git log (context break), say so, re-check the code, and fix `state.md` before continuing.
3. If `.ai/context/skeleton.md` is missing or behind HEAD, refresh it (refresh-skeleton skill) before relying on it.

## 2. How to explore (just-in-time, never dump)

Order of lookup, cheapest first:
1. `.ai/context/map.md` → where things live, entry points, flows already traced.
2. `.ai/context/flows/*.md` and `.ai/lld.md` → already-documented behaviour.
3. `.ai/context/skeleton.md` → classes / functions / routes with line numbers.
4. `grep` / `glob` for the exact symbol → read only the line range you need.
5. Read a whole file only when you will edit most of it.

Send independent searches together in one turn rather than one after another, and list matching files before reading any content.
Do not read entire directories "to get a feel". For big sweeps, delegate to a read-only subagent and keep only its conclusions.

## 3. Changing existing code

Before editing:
- **Impact analysis**: find every caller / importer / route / job / test of what you change (grep the symbol). State the blast radius in one or two lines.
- **Follow local patterns**: match the style, structure and libraries already used next to the code you touch.
- **No new dependencies, schema changes, public API changes or config changes without asking.**

While editing:
- Small, single-concern diffs. One task = one logical change.
- Tests first when feasible: write a **new** test that fails for the right reason, then make it pass.
- Never delete or weaken a test to make it pass. Changing a test that already exists in HEAD needs the human's approval (a hook asks). Never edit generated files; edit their source.

**Two-failure rule (no flailing).** If the same goal fails twice in a row with no forward progress (tests still red for the same reason, or new errors piling up):
1. Stop patching on top of patches.
2. Undo only your own edits for this attempt: restore the files listed under *Files touched this task* in `state.md` with `git checkout -- <files>`, or ask the human to run `/rewind`. Never `git reset --hard` or `git stash` the whole tree — the human may have uncommitted work.
3. Record in `state.md` → *Discarded hypotheses*: what you tried, the exact error, why it failed.
4. Try one genuinely different hypothesis. If that also fails, stop and ask the human, with both attempts summarised.

**Run tests quietly and fail-fast** so output does not flood context, e.g. `php artisan test --stop-on-failure`, `pytest -q -x`, `vitest run --reporter=dot --bail 1`, `npm test -- --bail 1`, `go test -failfast ./...`, `cargo test -q`, `ctest --output-on-failure --stop-on-failure`. Run a single test file while iterating; the full suite once before done.

## 4. Done means verified

A task is done only when all of these hold:
- Relevant tests, lint and type checks were **run** (not assumed) and pass, or the failure is unrelated and reported.
- For non-trivial changes, the `code-reviewer` subagent reviewed the diff and its findings were fixed or answered.
- Bug fixes and risky changes: the `qa-skeptic` subagent confirmed the reproduction test fails before and passes after, found no regressions, and its adversarial test failures were fixed or answered.
- High-risk changes (payments, auth, data migration, concurrency, money/finance logic) also get a second opinion from a different model (second-opinion skill) before merge.
- The project brain is updated (section 6).

## 5. Question protocol (ask, don't guess, when it matters)

Stop and ask the human when any of these is true:
- The requirement is ambiguous and the reasonable readings lead to different code.
- A secret, credential, environment value, external system access or test data is missing.
- Docs, tests and code contradict each other about intended behaviour.
- The action is destructive or hard to reverse (migrations, deletes, force pushes, prod deploys).
- Context break: memory says X, code says Y, and you cannot tell which is right.

How to ask: at most 4 short, multiple-choice style questions, recommended option first. Log every open question in `.ai/memory/questions.md`.
When the answer would not change the code much, do not ask: pick the most reasonable option, write it under **Assumptions** in `state.md`, and continue.

## 6. Keep the brain updated (the project folder `.ai/`)

- Task status changes → `tasks.md`. Every working turn that changed code → `memory/state.md` (the stop hook reminds you).
- Everything else (decisions, flows, LLD, testing, deployment, glossary, skeleton): the sync-brain skill says which file gets what.
- Keep `state.md` under ~60 lines: it is a scratchpad, not a log. Write facts with sources (`path/file.php:42`); mark guesses `(unverified)`.

## 7. Safety

- Never read, print or commit secrets (`.env*` except `.env.example`, keys, tokens). Refer to env vars by name only.
- Never `git push --force`, `git reset --hard` on shared branches, or run migrations / deploys against production.
- Never send client code or secrets to tools outside this repo's approved agents.

## 8. Context hygiene

- When the conversation gets long: update `state.md` first, then compact. After compaction, re-read `state.md` before acting.
- Prefer one task per session. Start a fresh session for an unrelated task.

## 9. End-of-task report (keep it short)

1. What changed (files, behaviour) 2. How it was verified (commands + result) 3. Risks / follow-ups 4. Brain files updated.
<!-- god-of-code:core:end -->
