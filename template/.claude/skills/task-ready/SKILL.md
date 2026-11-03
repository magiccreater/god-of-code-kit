---
name: task-ready
description: Check that a task has enough information to start work - why, what, testable acceptance criteria, and for bugs the steps to reproduce, expected vs actual and environment - score it, ask the human only what is missing, and record a readiness check. Use before starting any feature, change, bug fix or refactor, or when .ai/readiness.json mode is advisory or required.
argument-hint: "[task id (T-031) or task description]"
allowed-tools:
  - Bash(python3 .claude/god/decide/readiness.py *)
  - Bash(python .claude/god/decide/readiness.py *)
---

Task: $ARGUMENTS

Use `python` instead of `python3` on Windows. `R` below means `python3 .claude/god/decide/readiness.py`.

1. **Find or create the task.** Look it up in `.ai/tasks.md`; if it is new, add it (`T-###`, next free number) under *Todo*. Pick its type: `feature`, `bug`, `change` (to existing behaviour), `refactor` (behaviour stays the same) or `chore`. Mark `--risk high` for payments, money, auth, data migrations, deletes or concurrency.
2. **Create the spec** if `.ai/specs/<T-id>/spec.md` does not exist: `R new <T-id> --type <type> --title "<title>" [--risk high]`.
3. **Fill in what you already know**, from the human's request, the ticket text they gave, and the code (read just-in-time, rules.md §2). Write facts, not guesses:
   - Acceptance criteria as `- AC-001 (FR-001): Given ... When ... Then ...` with a concrete, observable result.
   - Bug steps as numbered actions; paste the exact error text into Actual / Evidence.
   - Anything you would have to guess, and that changes the code, becomes `[NEEDS CLARIFICATION: <question>]` under *Open questions*. Never invent requirements, numbers, versions or expected behaviour.
   - Remove the hint comments in sections you filled in; leave empty sections empty.
4. **Score it**: `R check <T-id>`.
5. **Act on the verdict:**
   - **READY** — set `Current task: <T-id>` and the Goal in `.ai/memory/state.md`, move the task to *In progress*, and continue with `/start-task <T-id>` if the human asked for the work.
   - **NEEDS_INFO** — ask the human the questions it printed (at most 5, recommended answer first when you have one, rules.md §5). Do not ask what you can find in the code. Write each answer into its section, add it under *Answers* with the date, replace answered `[NEEDS CLARIFICATION]` markers, then run `R check` again. Repeat until ready, or until the human says to proceed anyway: then record that under *Answers* and in state.md *Assumptions*, and say the task is starting below the readiness bar.
   - **NOT_READY** — the task is too thin to fix with a few answers. Show the human what is missing and ask them for the ticket, the bug report or a short description of the goal.
   - **OFF** — readiness is off (`.ai/readiness.json` mode); say so and continue.
6. Never edit `.ai/readiness.json` or the records in `.ai/review/readiness/` to make a task pass (lowering scores, skipping items, changing mode). Propose such changes to the human instead. A `[should]` item can stay weak when the human says it does not apply; write "none" or the reason in it.

`R status` shows mode, the current task and whether its last check is still fresh. `R verify <T-id>` tells whether the spec changed since it was checked. In required mode the pre-tool hook refuses edits to source files until the current task is ready.
