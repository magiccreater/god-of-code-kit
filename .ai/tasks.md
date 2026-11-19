# God of Code kit project tasks

This is the task board for the kit itself. The installer uses [the blank board](../template/.ai/tasks.md) for other repositories. Update an item's status and verification evidence when work lands. Move completed items to Done after their acceptance check passes.

## In progress

## Blocked

- [ ] T-012 · Enable and verify private Bedrock coding in Sydney · limpid-ai-dev-stack · since 2026-11-20 · The project has zero applied Qwen3 Coder Next requests and tokens per minute. Recheck the quota before running the private route.
- [ ] T-009 · Launch the Always Free Oracle inference VM in Sydney · limpid-ai-dev-stack · since 2026-11-19 · A1 host capacity was unavailable on the last check. Keep any retry within the free allocation.

## Todo

- [ ] T-006 · Enforce the configured monthly usage ceiling in the gateway · limpid-ai-dev-stack · since 2026-11-19 · Reserve estimated usage before model calls and cap output, retries, and concurrency. Include embeddings, storage, and gateway usage before credits. AWS Budgets tracks spend separately.
- [ ] T-007 · Persist per-repository task state and agent inboxes · coordination API and WSL workers · since 2026-11-19 · Prove that a reviewer can restart, recover an unread handoff, and review the same commit once. Gate all operations by repository access.
- [ ] T-008 · Retrieve approved project memory by keyword and meaning · Sydney retrieval service · since 2026-11-19 · Compare direct S3 Vectors hybrid retrieval against exact lookup using real file names, errors, and decisions. Return source references and measure cost and latency. Read access has been checked. Index creation and search still need verification.
- [ ] T-010 · Connect the personal Slack channel · local WSL configuration · since 2026-11-19 · Install a webhook for the chosen channel and verify delivery from an actual run. Keep the webhook and private task data out of Git and Slack notices.

- [ ] T-011 · Add standalone planning and research workflows · WSL supervisor · since 2026-11-19 · Deferred while the personal coding workflow is the priority.

## Done

- [x] T-005 · Connect the personal WSL Codex worker to the Sydney gateway · limpid-ai-dev-stack and god-of-code-kit · Live public free-auto proved IAM-authenticated streaming, a shell tool call, a local edit and check, and clean patch application. [Gateway](https://github.com/magiccreater/limpid-ai-dev-stack/pull/7) and [WSL bridge](https://github.com/magiccreater/god-of-code-kit/pull/6).
- [x] T-001 · Ship the per-repo task board, readiness checks, and review rules · template/.ai and template/.claude · verified by the kit tests and [PR #1](https://github.com/magiccreater/god-of-code-kit/pull/1).
- [x] T-002 · Isolate Codex workers and sanitize inference requests from WSL · WSL supervisor · synthetic inference smoke test verified a tool call, redaction, a patch, and clean application. [PR #2](https://github.com/magiccreater/god-of-code-kit/pull/2).
- [x] T-003 · Validate AWS-hosted inference in Sydney · disposable EC2 test · WSL received a live response through the gateway. The VM, security group, and storage were cleaned up. The AWS Free Plan project has a monthly usage-monitoring budget.
- [x] T-004 · Add Slack status notices to coding and review runs · WSL supervisor · optional metadata-only delivery covered by mocked webhook tests.
