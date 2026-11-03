# Task specs (`.ai/specs/<T-id>/spec.md`)

One folder per task. The spec says why the task exists, what "done" looks like, and (for bugs) how to
reproduce it, so that work starts from facts instead of guesses. The `task-ready` skill creates it, scores
it and asks for what is missing; the `converge` skill compares the finished code with it.

```bash
python3 .claude/god/decide/readiness.py new T-031 --type bug --title "Partial refund fails" --risk high
python3 .claude/god/decide/readiness.py check T-031      # score, missing items, up to 5 questions
python3 .claude/god/decide/readiness.py trace T-031      # which acceptance criteria a test names
python3 .claude/god/decide/readiness.py status
```

## What each type needs

| Type | Must have | Should have |
|---|---|---|
| feature | why, what, testable acceptance criteria | every FR covered by an AC, out of scope, edge cases, non-functional, dependencies |
| bug | why, steps to reproduce (2+ numbered), expected, actual (different from expected), environment | evidence (exact error/log), impact, acceptance criteria, dependencies |
| change | why, what, what must not change, acceptance criteria | FR coverage, out of scope, edge cases, dependencies |
| refactor | why, what, what must not change, existing tests (safety net), acceptance criteria | — |
| chore | why, what | — |

High risk (`risk: high`: payments, auth, money, migrations, concurrency) also needs a rollback plan and
should name reviewers. Any open `[NEEDS CLARIFICATION: ...]` marker blocks "ready".

## Scoring

Each item is ok (full weight), weak (half) or missing (none). Placeholders (`TODO`, `TBD`, `...`) and
HTML comments count as empty. "none" is a valid answer for out of scope, edge cases, non-functional and
dependencies.

- **ready**: score ≥ 80 (`ready_score`), every must-have ok, no open clarification.
- **needs_info**: otherwise; answer the questions (at most 5), write them into the spec, check again.
- **not_ready**: score < 50 (`ask_score`); the task needs rewriting, not a few answers.

An acceptance criterion is checkable when it is Given/When/Then or names an observable result (a number,
a quoted value, "returns", "shows", "is rejected"...). Vague words ("fast", "user-friendly", "works
correctly") with nothing measurable make it weak.

## Acceptance criteria and tests

Write criteria as `- AC-001 (FR-001): Given ... When ... Then ...`. Name or comment each test with the
criterion it proves (`test_ac_001_partial_refund_updates_balance`, `it("AC-001 ...")`, `# AC-001`).
`readiness.py trace` and the decision gate use those names: a criterion no test names caps the gate at
needs_review.

Records of each check go to `.ai/review/readiness/<T-id>.json`, bound to the spec's SHA-256: editing the
spec makes the record stale, so check again after any change.
