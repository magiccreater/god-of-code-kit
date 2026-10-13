@AGENTS.md

## Claude Code specifics

- A session-start hook loads `.ai/memory/state.md`, open tasks and freshness warnings into context. Treat them as working memory and verify against code.
- A stop hook reminds you to update `.ai/memory/state.md` and `.ai/tasks.md` when code changed during the turn.
- Skills: `/onboard-repo`, `/refresh-skeleton`, `/trace-flow`, `/start-task`, `/sync-brain`, `/write-lld`, `/ops-docs`, `/second-opinion`.
- Use the `code-reviewer` subagent on non-trivial diffs before calling a task done. Use read-only Explore subagents for wide searches.
- Use plan mode for tasks touching more than ~3 files or anything in payments, auth, migrations or finance logic.
