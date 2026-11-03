---
name: converge
description: After implementing a task, compare the code and tests with its spec (.ai/specs/<T-id>/spec.md) - every requirement built, every acceptance criterion proved by a named test, nothing out of scope, bug reproduced - and append any gaps as new tasks. Use after implementation and before code review and the ready-gate.
argument-hint: "[task id, default: Current task in state.md]"
allowed-tools:
  - Bash(python3 .claude/god/decide/readiness.py *)
  - Bash(python .claude/god/decide/readiness.py *)
  - Bash(git diff *)
  - Bash(git status)
---

Task: $ARGUMENTS (default: *Current task* in `.ai/memory/state.md`). `R` means `python3 .claude/god/decide/readiness.py`.

This step only finds gaps and records them. It does not rewrite the spec's requirements or acceptance criteria, and it does not fix code: fixing is the next step of `/start-task`.

1. **Read the spec** and the change: `git diff` against the task's base (or `git diff HEAD` plus new files from `git status`).
2. **Trace**: `R trace <T-id>` lists the acceptance criteria that no test names.
3. **Check each item**, citing `path:line`:
   - every `FR-xxx` is implemented;
   - every `AC-xxx` has a test that names it and asserts the *Then* part (not just that the code runs). Run those tests (quiet, fail-fast);
   - nothing in *Out of scope* or *Must not change* was changed;
   - edge cases listed in the spec are handled or tested;
   - for bugs: a test follows the *Steps to reproduce* and fails on the base code (the `qa-skeptic` agent proves this);
   - for high risk: the rollback plan still works with the change as built.
4. **Append gaps** under *Tasks* in the spec, never editing existing lines: `- [ ] G-1 (AC-002): no test asserts the refund email is sent — add test_ac_002_...`. If a gap is really a missing or wrong requirement, add a `[NEEDS CLARIFICATION: ...]` under *Open questions* and ask the human instead of changing the requirement yourself.
5. **Write the result** under *Convergence*, one dated line:
   - no gaps: `- 2026-11-03: converged — 4/4 AC tested (tests/test_refund.py), 0 gaps`
   - gaps: `- 2026-11-03: not converged — 2 gaps (G-1, G-2)`
6. Report the gaps. If there are any, fix them (back to `/start-task` step 6) and run `/converge` again. The decision gate caps its verdict at needs_review while any AC has no test, and advises running converge until the spec says *converged*.

Editing the spec makes its readiness record stale; that is expected after convergence. Run `R check` again only if requirements or acceptance criteria changed (they should not have, in this step).
