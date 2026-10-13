---
name: start-task
description: Run a coding task (new feature, change to existing code, bug fix, refactor) through the full loop - clarify, impact analysis, plan, tests first, implement, verify, review, update the project brain.
argument-hint: "[task description or task id from .ai/tasks.md]"
disable-model-invocation: true
---

Task: $ARGUMENTS

1. **Register** — find or create the task in `.ai/tasks.md` (`T-###`), move it to *In progress*. Set Goal / Current task / Next action in `.ai/memory/state.md`.
2. **Load context just-in-time** — read the relevant flow docs and `lld.md` sections first, then skeleton + grep, then line ranges. If no flow doc exists for business logic you will change, run the trace-flow skill first.
3. **Clarify** — apply the question protocol (rules.md §5). Ask only questions whose answers change the code; otherwise record assumptions in state.md.
4. **Impact analysis** — list callers, routes, jobs, tests and data affected; state the blast radius. For changes to existing behaviour, note what must not change.
5. **Plan** — at most ~7 steps. If the task touches more than ~3 files, a DB schema, payments/auth/finance logic, or a public API: present the plan and wait for approval.
6. **Tests first** — add or update tests that capture the intended behaviour (and the bug, for fixes). Run them and confirm they fail for the right reason.
7. **Implement** in small steps, following local patterns. Re-run the targeted tests after each step.
8. **Verify** — run the full relevant suite, lint and type checks from rules.md §0. Fix what you broke; report unrelated failures.
9. **Review** — for non-trivial diffs, use the `code-reviewer` subagent. Fix or answer each finding. For high-risk areas, suggest `/second-opinion`.
10. **Update the brain** — run the sync-brain skill (tasks → Done, state.md, decisions, flows, lld, testing/deployment as needed).
11. **Report** with the rules.md §9 format. Propose a commit message (conventional commits); commit only if asked.
