# Project State Service low-level design

**Status** Proposed. The AWS pilot and the latency targets below still need verification. The 100 ms warm p95 latency target is an unvalidated hypothesis to be measured and validated under T-020, particularly given the architectural tension of avoiding connection pools (paying per-request TLS + login overhead or RDS Data API latency) so Aurora can auto-pause.

## Scope

Provide one independent, project-scoped source of truth for agent sessions, tasks, handoffs, approved memory, structured run logs, model attempts, and Laya routing decisions. A real-time chatbot and WSL workers use the same state API. LiteLLM can run in Sydney, another approved environment, or locally. Each client configures a state URL and an inference URL separately. Model providers receive only context approved for their route.

The initial deployment is a Python HTTP API and PostgreSQL in WSL Docker Compose, bound to loopback. Workers reach it through the WSL supervisor. The AWS candidate is a separate stack with API Gateway, Lambda and a private Aurora Serverless PostgreSQL writer in Sydney. The stack, database, networking, identity, and deployment pipeline are independent of the inference gateway. Aurora is a hosting option for the same PostgreSQL schema and API. Keep the pilot within an active AWS Free Plan and the existing US$20 monthly pre-credit target. AWS lists up to 4 ACUs and 1 GiB per Aurora PostgreSQL Serverless Free Plan cluster. Confirm remaining credits, account eligibility and the plan end date. Schedule a tested export to WSL before credits or the Free Plan expire. Benchmark and approve projected usage before provisioning a long-lived instance.

## Components and data flow

1. The IDE or chatbot opens a project session and creates an assignment. The supervisor claims it, builds an isolated worktree, and checkpoints the task before starting the agent.
2. The supervisor makes one context request with the current task, latest handoff, a bounded history window and relevant approved memory. The WSL relay redacts context and enforces the provider policy before sending it to LiteLLM.
3. LiteLLM runs inference and records the actual provider/model when available. It records each attempt and captures Laya results, timeouts, abstentions, rule fallbacks and the selected route. Laya is invoked by the router. LiteLLM's telemetry writer can append routing events only.
4. The developer writes a handoff for the exact commit, Git tree or immutable patch plus base digest it used. It includes test evidence and blockers. The reviewer has its own claim and writes a separate result tied to that revision. A revised patch requires a fresh review. GitHub remains the authority for merge approval.
5. The state API commits messages and handoffs before delivering live notifications. The chatbot subscribes to project-authorized updates and can replay missed records after reconnecting.

The [PR governance design](pr-governance-lld.md) uses the state service for portable audit history. GitHub retains merge authority and can enforce the verifier independently of the state service.

## PostgreSQL schema

Use versioned SQL migrations and stable UUIDs. Include project_id in composite keys and foreign keys for all project-owned rows. Use UTC timestamps. Enforce project membership through the API and PostgreSQL row-level security (RLS). Note that RLS isolates projects from each other; worktrees mapped to the same project share that project's scope. Use a non-owner request role and transaction-scoped authorization (`SET LOCAL app.current_project_id = :project_id`) so pooled connections cannot retain the previous request's project scope. Internal worker and telemetry identities have separate grants.

| Table or group | Key fields and indexes |
|---|---|
| projects, project_members | Project UUID, canonical repository identity, repository aliases and role assignments. Register a remote or an explicit UUID for local-only repositories. Multiple worktrees resolve to the same project. |
| sessions, checkpoints | Project and session IDs, status, task reference, last durable sequence, snapshot reference, checkpoint content and version. Index sessions by project and last activity. |
| tasks, assignments | Project and task IDs, acceptance criteria, worker role, status, artifact revision, lease owner, fence token and lease deadline. Index claimable work by project, status and time. |
| messages, inbox_cursors, reviews | Project and stream IDs, monotonic stream sequence, sender, recipient, run ID, revision, reviewed evidence and reply reference. Unique project + stream + sequence. Index inboxes by project, recipient and sequence. |
| memory_items | Project, text, approval state, source reference, verified revision, verification time and superseded item. Use a GIN text index plus exact indexes on normalized artifact paths and error identifiers. |
| model_attempts, routing_decisions, run_events | Project, task, session, run, request and event IDs. Unique producer + event ID within a project. Store attempt status, model/provider, token usage when reported, latency, Laya model/version, score or abstention, and routing reason. Index by project and run/request ID. |
| event_outbox, idempotency_keys | Outbox records committed alongside domain changes. Unique project + actor + idempotency key. Store a request fingerprint and result reference and reject key reuse with a different payload. |
| artifacts | Project, artifact ID, content digest, size, visibility and locator. Store bounded payloads in PostgreSQL for the pilot. Move larger patches and reports to a portable object-storage adapter when needed. |

Store session content and operational telemetry under separate permissions. Operational telemetry excludes raw prompts, tool output, diffs, and credentials. Workers store approved conversation checkpoints and artifacts under project retention and deletion rules. Model calls store usage and outcome metadata. Record unavailable usage as null. Configure transcript, telemetry, artifact and backup retention before enabling real private data.

## Implementation decisions (T-017)

The first T-017 PR resolves three primary design choices:

1. **API Framework: FastAPI with Uvicorn**
   - High-performance asynchronous Python HTTP framework.
   - Native Pydantic schema validation for request payloads and responses.
   - Built-in OpenAPI specification generation and clean router modularity.
   - Standardized on Uvicorn, aligning directly with the existing dev stack (`aws/litellm-router/colocation/deploy.py` and `shared`).

2. **Database Migration Tool: Alembic**
   - Standard Python migration manager for PostgreSQL.
   - Versioned, sequential migration scripts in `alembic/versions`.
   - Full programmatic CLI support (`alembic upgrade head`, downgrade validation), integrated directly into local WSL Docker Compose startup and test fixtures.

3. **Local Credentials & Project-Scoped Auth in WSL**
   - Local tokens: Short-lived HMAC-SHA256 signed bearer tokens (JWT) generated with a local secret (`STATE_JWT_SECRET` in `.env`).
   - Token payload: `sub` (caller identity), `project_id` (mandatory project UUID), `role` (`worker`, `telemetry`, or `admin`), and `exp` (15–60 minute expiry).
   - RLS integration: The State API extracts `project_id` from the verified token and executes `SET LOCAL app.current_project_id = :project_id` within the request's transaction. PostgreSQL RLS policies enforce `project_id = current_setting('app.current_project_id')::uuid`. Multiple worktrees for a repo share the same project ID and are therefore within the same project isolation boundary.
   - AWS parity: The interface seamlessly maps to AWS IAM / STS temporary credentials or an API Gateway Lambda authorizer providing equivalent project-scoped claims.

## API and concurrency

All examples below are under /v1/projects/{project_id}. Version the API independently from the persistence adapter.

| Endpoint | Behavior |
|---|---|
| POST /tasks, POST /sessions | Create project work and a session. Require an idempotency key. Return IDs and current versions. |
| POST /assignments/claim, POST /assignments/{id}/heartbeat | Atomically claim eligible work with a lease and fencing token. Renew only the current lease. |
| POST /assignments/{id}/handoff, POST /reviews | Bind evidence to the exact revision. Reject expired or stale fencing tokens. Publish a durable inbox event in the same transaction. Record at most one review outcome per assignment and revision. |
| POST /sessions/{id}/checkpoints, GET /sessions/{id} | Write using an expected version. On conflict, fetch and reconcile. Read the latest checkpoint with a bounded window of following events. |
| POST /messages, GET /events?after={cursor} | Persist a message and return its sequence only after commit. Replay ordered, paginated events after the last acknowledged cursor. Acknowledge positions per authorized recipient and stream. |
| PUT /streams/{id}/cursor | Advance the authenticated recipient's cursor monotonically to a sequence they can access. |
| POST /context, POST /memory/search | Return task, latest handoff, recent checkpoint and top approved memory hits in one bounded payload. Return source references and a cursor for additional results. |
| POST /telemetry/batch | Append schema-validated model-attempt, decision and run events with stable event IDs. Do not grant this identity access to chat transcripts or memory. |

Use one shared transaction for claiming or changing a lease. Completion checks the current fence and revision. Network delivery may repeat. Deduplicate writes and state transitions by their keys. An external provider call can have an unknown result after a timeout. Record it as unknown and retain its attempt ID. Retry a model call only when provider behavior and the task budget permit it.

Expose `STATE_BASE_URL` separately from the inference configuration. Preserve session IDs across inference switches. A model switch reconstructs the next request from the last portable checkpoint and tool evidence. Mark any in-flight attempt interrupted or unknown and recover from the last durable checkpoint.

## Realtime delivery and idle behavior

- Use API Gateway WebSockets for the AWS chatbot. Authenticate the connection, authorize subscriptions by project and session, and recheck access before pushing sensitive updates. Use short-lived connection credentials and a DynamoDB connection registry with expiry for connection IDs and memberships. Store chat content in PostgreSQL.
- Write the event and outbox row in one transaction. After commit, enqueue a push notification. The dispatcher sends it to current authorized subscribers. Push can repeat and can lag after a sender crash. Clients deduplicate by event ID and replay by cursor on reconnect, detection of a sequence gap, or an active catch-up request. If an enqueue fails and no newer activity arrives, a connected client recovers that final event on its next sync or reconnect. API activity reconciles pending outbox rows in bounded batches. This keeps recovery possible if notification enqueue fails after commit. Idle clients do not poll PostgreSQL.
- Show a waking state on the first project open or chat request after idle. Preserve the request's idempotency key through resume and retry. Keep idle sockets independent from database connections. Benchmark direct, short-lived PostgreSQL connections and the RDS Data API where supported. Use the option that meets warm latency and lets Aurora actually auto-pause. Avoid a database poller, maintenance connection or pool that prevents pausing.
- Keep writes that must persist before tool execution synchronous. Record inference telemetry outside the reply's critical path. The WSL sender starts with a durable local spool. The AWS LiteLLM sender uses a bounded durable AWS queue with stable event IDs, retry and a dead-letter queue. Measure and surface delivery lag. An enqueue failure produces an operational error signal. Test failure injection so missing audit events are visible. Sessions retain their durable checkpoint even if telemetry is delayed.

## Warm performance and search

Measure from the WSL client to the active State API, excluding model generation and database wake-up. Use a representative corpus across two projects and concurrent chatbot, worker and telemetry traffic. Publish sample count, data size, concurrency, p50, p95, p99, errors and cold wake time separately.

The initial warm p95 latency targets are testable hypotheses to be verified in T-020, not validated facts. The architectural decision to avoid persistent connection pools (ensuring Aurora Serverless v2 can auto-pause during idle) means requests must pay the penalty of a fresh TLS handshake and Postgres login (or the latency of the RDS Data API), alongside API Gateway and Lambda overhead. T-020 will measure whether 100 ms is achievable under these constraints.

| Operation | Initial warm p95 target (Hypothesis) |
|---|---:|
| Resume a session or fetch an unread handoff | 100 ms |
| Search approved project memory | 200 ms |
| Deliver a persisted message to a connected client | 250 ms |

Use bounded result windows and project-first lookups. Search already-approved text with PostgreSQL full-text search and a GIN index. Use exact indexes for file paths, symbols and error IDs. Evaluate semantic search with a labelled repo query set before adding embeddings or a vector index. Precompute any embeddings off the chatbot path. Measure SQL plans and results under concurrent writes before adding a separate cache or search service.

## Security and operational checks

- Authenticate the WSL/agent client and service publishers. Scope read/write access per project and operation. Keep the database private. AWS service calls can use IAM, and the portable API supports short-lived application credentials for non-AWS clients. Use TLS for remote calls. Derive project access from the authenticated identity and validate the requested scope on every call.
- Keep memory candidates pending until an authorized owner approves them. Preserve provenance and verification status. Retrieved memory and tool output are inputs the worker must treat as untrusted. Prompt text never grants a provider permission or a merge approval.
- Measure storage, requests, connections, wake-ups and pre-credit usage. Apply per-project request, payload and retention limits. Use a private AWS test environment, no paid-plan upgrade, and confirm engine/region availability, auto-pause and expected charges before rollout. Monitor active compute and storage separately. AWS Budgets is an alerting mechanism.
- Export a versioned database backup plus an artifact manifest and verify a restore on a second host. Recreate roles from migrations and rotate service credentials. For state migration, fence writes on the old service, transfer the final changes, verify sequence high-water marks, digests and permissions, then switch the state URL. Keep a rollback copy under the agreed retention policy.

## Delivery and acceptance

1. Deploy the WSL API and PostgreSQL using synthetic data. Verify migrations, membership isolation, composite foreign keys and backup/restore.
2. Move worker checkpoints and handoffs behind the API. Run two projects concurrently. Crash and restart a reviewer, replay its unread inbox and prove it reviews the intended revision without recording a duplicate outcome.
3. Publish LiteLLM attempt and Laya events. Simulate a provider fallback and a temporary state outage. Verify both attempts, the routing reason and eventual delivery of buffered events.
4. Add approved memory search and real-time chatbot subscriptions. Simulate disconnects, outbox enqueue loss and revoked access. Show that catch-up recovers committed messages without crossing project boundaries.
5. Deploy a small AWS pilot only after the local tests pass. Verify auto-pause, separate cold wake from warm measurements, and compare cost to the budget. Start a Sydney-backed session and resume with local inference against the same state endpoint. Restore the state on another host and repeat recovery.

Design references

- [Project task board](tasks.md)
- [AWS RDS Free Tier and Aurora cluster limits](https://aws.amazon.com/rds/free/)
- [AWS Aurora auto-pause and resume](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2-auto-pause.html)
- [PostgreSQL preferred text search index types](https://www.postgresql.org/docs/16/textsearch-indexes.html)
- [PostgreSQL export and restore](https://www.postgresql.org/docs/current/app-pgdump.html)
