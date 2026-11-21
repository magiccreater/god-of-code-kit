# God of Code kit project tasks

This is the task board for the kit itself. The installer uses [the blank board](../template/.ai/tasks.md) for other repositories. Update an item's status and verification evidence when work lands. Move completed items to Done after their acceptance check passes.

## In progress

## Blocked

- [ ] T-012 · Enable and verify private Bedrock coding in Sydney · limpid-ai-dev-stack · since 2026-11-20 · The project has zero applied Qwen3 Coder Next requests and tokens per minute. Recheck the quota before running the private route.
- [ ] T-009 · Launch the Always Free Oracle inference VM in Sydney · limpid-ai-dev-stack · since 2026-11-19 · A1 host capacity was unavailable on the last check. Keep any retry within the free allocation.

## Todo

### Project State Service

See the [low-level design](project-state-lld.md). Build and prove the WSL path before provisioning a persistent AWS database. The acceptance targets are warm p95 of 100 ms for session/inbox reads, 200 ms for memory search, and 250 ms for message delivery. Measure wake-up separately.

- [ ] T-017 · Define the independent State API and PostgreSQL schema · Ship migrations, WSL Compose, stable project IDs and project-scoped credentials. Prove cross-project isolation and local backup/restore.
- [ ] T-007 · Persist repo-scoped sessions, tasks and inboxes · Depends on T-017. Integrate worker checkpoints, leased assignments and revision-bound handoffs. Restart a reviewer and recover the same assignment with one recorded result.
- [ ] T-018 · Record LiteLLM attempts and Laya decisions · Depends on T-017 and T-007. Correlate model retries, fallbacks, latency and reported usage. Verify durable buffering during an outage and idempotent delivery after recovery.
- [ ] T-008 · Search approved project memory · Depends on T-017. Start with exact lookup and PostgreSQL full-text indexing. Return source references and benchmark representative file names, errors and decisions. Evaluate semantic retrieval after measuring recall gaps.
- [ ] T-019 · Connect the real-time chatbot · Depends on T-007 and T-008. Add authorized WebSocket subscriptions, replay from the last acknowledged cursor, and a waking state. Test reconnect, duplicate delivery, outbox recovery and revoked access.
- [ ] T-020 · Validate the independent AWS deployment · Depends on T-018 and T-019. Verify Sydney Aurora version, Free Plan eligibility and pre-credit budget. Benchmark the warm targets from WSL across two projects, idle auto-pause, cold wake and concurrent message delivery.
- [ ] T-021 · Prove session and storage portability · Depends on T-020. Resume the same session after switching Sydney inference to local. Restore state on another host and verify checkpoints, unread handoffs, memory, artifacts and model history before cutover.

### Other backlog

- [ ] T-015 · Evaluate Laya on coding decisions · Collect approved task labels and measure incorrect ready verdicts and tier recommendations on held-out cases before enabling automatic model selection or fitting a checkpoint.

- [ ] T-014 · Ship a standalone WSL runner · Rust launcher preview · The opt-in Cargo package forwards to the existing kit launcher. A future release needs to bootstrap its own worker and relay and pass the existing sandbox, gateway, and patch checks.

- [ ] T-006 · Enforce the configured monthly usage ceiling in the gateway · limpid-ai-dev-stack · since 2026-11-19 · Reserve estimated usage before model calls and cap output, retries, and concurrency. Include embeddings, storage, and gateway usage before credits. AWS Budgets tracks spend separately.
- [ ] T-010 · Connect the personal Slack channel · local WSL configuration · since 2026-11-19 · Install a webhook for the chosen channel and verify delivery from an actual run. Keep the webhook and private task data out of Git and Slack notices.

- [ ] T-011 · Add standalone planning and research workflows · WSL supervisor · since 2026-11-19 · Deferred while the personal coding workflow is the priority.

## Done

- [x] T-016 · Route public coding requests through Sydney LiteLLM and Laya · Live signed WSL request streamed a reply through the free fallback and CloudWatch verified the server-side Laya invocation. WSL tests cover selection using the score and separate provider permissions.

- [x] T-013 · Replace Codex CLI with the kit's Python worker · WSL supervisor · A native worker edited and verified a synthetic file over two live Sydney free-auto turns, then produced a patch that applied cleanly. The WSL tests also cover both gateway protocols with synthetic responses.

- [x] T-005 · Connect the personal WSL Codex worker to the Sydney gateway · limpid-ai-dev-stack and god-of-code-kit · Live public free-auto proved IAM-authenticated streaming, a shell tool call, a local edit and check, and clean patch application. [Gateway](https://github.com/magiccreater/limpid-ai-dev-stack/pull/7) and [WSL bridge](https://github.com/magiccreater/god-of-code-kit/pull/6).
- [x] T-001 · Ship the per-repo task board, readiness checks, and review rules · template/.ai and template/.claude · verified by the kit tests and [PR #1](https://github.com/magiccreater/god-of-code-kit/pull/1).
- [x] T-002 · Isolate Codex workers and sanitize inference requests from WSL · WSL supervisor · synthetic inference smoke test verified a tool call, redaction, a patch, and clean application. [PR #2](https://github.com/magiccreater/god-of-code-kit/pull/2).
- [x] T-003 · Validate AWS-hosted inference in Sydney · disposable EC2 test · WSL received a live response through the gateway. The VM, security group, and storage were cleaned up. The AWS Free Plan project has a monthly usage-monitoring budget.
- [x] T-004 · Add Slack status notices to coding and review runs · WSL supervisor · optional metadata-only delivery covered by mocked webhook tests.
