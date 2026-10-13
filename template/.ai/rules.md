# Rule book (read first, every session)

This is the operating manual for any AI agent working in this repo (Claude Code, Antigravity/Gemini, others).
Project-specific facts live in the other files under `.ai/`. Keep this file under ~150 lines.

## 0. Project commands (fill in during onboarding)

| Action | Command |
|---|---|
| Install deps | `TODO` |
| Run app locally | `TODO` |
| Unit tests | `TODO` |
| Single test | `TODO` |
| Lint / format | `TODO` |
| Type check / static analysis | `TODO` |
| Build | `TODO` |

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

Do not read entire directories "to get a feel". For big sweeps, delegate to a read-only subagent and keep only its conclusions.

## 3. Changing existing code

Before editing:
- **Impact analysis**: find every caller / importer / route / job / test of what you change (grep the symbol). State the blast radius in one or two lines.
- **Follow local patterns**: match the style, structure and libraries already used next to the code you touch.
- **No new dependencies, schema changes, public API changes or config changes without asking.**

While editing:
- Small, single-concern diffs. One task = one logical change.
- Tests first when feasible: write or update a test that fails for the right reason, then make it pass.
- Never delete or weaken a test to make it pass. Never edit generated files; edit their source.

## 4. Done means verified

A task is done only when all of these hold:
- Relevant tests, lint and type checks were **run** (not assumed) and pass, or the failure is unrelated and reported.
- For non-trivial changes, the `code-reviewer` subagent reviewed the diff and its findings were fixed or answered.
- High-risk changes (payments, auth, data migration, concurrency, money/finance logic) get a second opinion from a different model (second-opinion skill) before merge.
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

| When | Update |
|---|---|
| Task starts / changes status | `tasks.md` (In progress / Todo / Blocked / Done) |
| End of every working turn that changed code | `memory/state.md` (goal, facts, discarded hypotheses, blocker, next action) |
| A design or technology choice is made | `memory/decisions.md` (one ADR entry) |
| A business flow is understood | `context/flows/<flow>.md` + link in `context/map.md` |
| Module internals change (data model, contracts, sequences) | `lld.md` |
| Build / deploy / env knowledge discovered | `deployment.md` |
| Test commands, fixtures, gaps discovered | `testing.md` |
| New domain term | `glossary.md` |
| Files / classes added, moved or renamed | refresh `context/skeleton.md` |

Keep `state.md` under ~60 lines: it is a scratchpad, not a log. Move finished detail into the right file.
Write facts with sources (`path/file.php:42`), not guesses. Mark unverified items `(unverified)`.

## 7. Safety

- Never read, print or commit secrets (`.env*` except `.env.example`, keys, tokens). Refer to env vars by name only.
- Never `git push --force`, `git reset --hard` on shared branches, or run migrations / deploys against production.
- Never send client code or secrets to tools outside this repo's approved agents.

## 8. Context hygiene

- When the conversation gets long: update `state.md` first, then compact. After compaction, re-read `state.md` before acting.
- Prefer one task per session. Start a fresh session for an unrelated task.

## 9. End-of-task report (keep it short)

1. What changed (files, behaviour) 2. How it was verified (commands + result) 3. Risks / follow-ups 4. Brain files updated.
