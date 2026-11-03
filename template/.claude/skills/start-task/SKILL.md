---
name: start-task
description: Run a coding task (new feature, change to existing code, bug fix, refactor) through the full loop - clarify, impact analysis, plan, tests first, implement, verify, review, update the project brain.
argument-hint: "[task description or task id from .ai/tasks.md]"
disable-model-invocation: true
---

Task: $ARGUMENTS

1. **Register and check readiness** — run the task-ready skill for this task: it finds or creates the task in `.ai/tasks.md` (`T-###`) and its spec `.ai/specs/<T-id>/spec.md`, scores it, and asks only what is missing (why, what, acceptance criteria; for bugs, the steps to reproduce, expected vs actual, environment). Continue when it is ready, or when the human says to proceed anyway (record that as an assumption). Then move the task to *In progress* and set Goal / Current task / Next action in `.ai/memory/state.md`.
2. **Load context just-in-time** — read the relevant flow docs and `lld.md` sections first, then skeleton + grep, then line ranges. If no flow doc exists for business logic you will change, run the trace-flow skill first.
3. **Clarify** — the spec answered the product questions; ask only what the code raises (rules.md §5). Record new answers in the spec under *Answers*, and other assumptions in state.md.
4. **Impact analysis** — list callers, routes, jobs, tests and data affected; state the blast radius. For changes to existing behaviour, note what must not change.
5. **Plan** — at most ~7 steps. If the task touches more than ~3 files, a DB schema, payments/auth/finance logic, or a public API: present the plan and wait for approval.
6. **Tests first** — add **new** tests that capture each acceptance criterion, named after it (`test_ac_001_...`, `it("AC-001 ...")`); for bugs, a test that follows the spec's *Steps to reproduce*. Run them and confirm they fail for the right reason. Changing an existing test needs the human's approval.
7. **Implement** in small steps, following local patterns. Re-run the targeted tests (quiet, fail-fast) after each step. Apply the two-failure rule (rules.md §3) instead of stacking patches.
8. **Verify** — run the full relevant suite, lint and type checks from rules.md §0. Fix what you broke; report unrelated failures.
9. **Converge** — run the converge skill: every requirement built, every acceptance criterion proved by a named test, nothing out of scope changed. Fix its gaps (back to step 6) until the spec says *converged*.
10. **Review** — for non-trivial diffs, use the `code-reviewer` subagent. For bug fixes and risky changes, also use the `qa-skeptic` subagent (fail-before/pass-after + adversarial tests in a scratch worktree). Fix or answer each finding; adopt its failing adversarial tests as real tests. For payments, auth, finance, migrations or concurrency, suggest `/second-opinion` too. If the decision gate is on (`.ai/decision-gate.json` mode advisory or required), run the ready-gate skill last and handle its "Next" items.
11. **Update the brain** — run the sync-brain skill (tasks → Done, state.md, decisions, flows, lld, testing/deployment as needed).
12. **Report** with the rules.md §9 format. Propose a commit message (conventional commits); commit only if asked.
