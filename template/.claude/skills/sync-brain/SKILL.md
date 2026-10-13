---
name: sync-brain
description: Update the project brain in .ai/ after work - task status, working state, decisions, flows, LLD, testing and deployment notes, glossary, skeleton. Use at the end of a task or turn that changed code, before compacting, or when asked to save progress.
---

1. Look at what changed: `git status`, `git diff --stat`, and this session's work. Ignore `.ai/` itself.
2. **tasks.md** — move tasks between In progress / Blocked / Todo / Done. Add follow-ups discovered. Keep Done to the last 20 (move older lines to `.ai/memory/archive.md`).
3. **memory/state.md** — rewrite (do not append) to reflect *now*: goal, confirmed facts with `file:line`, discarded hypotheses, assumptions, blocker, next action, files touched. Keep under ~60 lines; move finished detail to the right file below.
4. **memory/decisions.md** — add an entry for any real design choice made.
5. **context/flows/** — update flows whose behaviour changed; fix cited line numbers that moved.
6. **lld.md** — update data model, contracts, sequences, state machines for changed modules.
7. **testing.md / deployment.md** — record new commands, fixtures, env var names, migration or rollout steps.
8. **glossary.md / memory/questions.md** — new terms; answered questions ticked with the answer.
9. **Skeleton** — if files or classes were added, moved or renamed, run the refresh-skeleton skill.
10. Report in one or two lines which files were updated.

Write facts, not narration. Never copy secrets or env values into `.ai/`.
