<!-- god-of-code:begin -->
@AGENTS.md

## Claude Code specifics

- A session-start hook loads `.ai/memory/state.md`, open tasks and freshness warnings into context. Treat them as working memory and verify against code.
- A stop hook reminds you to update `.ai/memory/state.md` and `.ai/tasks.md` when code changed during the turn.
- A pre-tool hook asks the human before any change to a test file that already exists in HEAD, and before a commit that changes source code without tests.
- Skills: `/onboard-repo`, `/refresh-skeleton`, `/trace-flow`, `/task-ready`, `/start-task`, `/converge`, `/sync-brain`, `/write-lld`, `/ops-docs`, `/second-opinion`, `/ready-gate`.
- In decision-gate required mode, `git push` and `gh pr create` are denied without a fresh "ready" receipt from `/ready-gate`.
- In readiness required mode (`.ai/readiness.json`), edits to source files are denied until the current task has a fresh "ready" check from `/task-ready`.
- Use the `code-reviewer` subagent on non-trivial diffs before calling a task done, and the `qa-skeptic` subagent on bug fixes and risky changes. Use read-only Explore subagents for wide searches.
- Use plan mode for tasks touching more than ~3 files or anything in payments, auth, migrations or finance logic.
<!-- god-of-code:end -->
