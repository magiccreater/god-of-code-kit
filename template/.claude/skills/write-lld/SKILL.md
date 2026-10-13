---
name: write-lld
description: Write or update the low-level system design for one module of this repo in .ai/lld.md - components, data model, contracts, sequences, state machines, business rules, failure modes - with file:line sources. Use when asked for LLD, before a large change to a module, or when onboarding someone to a module.
argument-hint: "[module name or path, e.g. 'payments' or app/Services/Finance]"
effort: high
---

Module: $ARGUMENTS

1. Locate the module with `.ai/context/map.md` and the skeleton; list its files. Confirm scope with the human if the boundary is unclear.
2. Read flows already traced for this module (`.ai/context/flows/`). Trace missing key flows with the trace-flow skill.
3. Gather, citing `path:line` for each fact:
   - **Components**: classes/files → responsibility → key public methods
   - **Data model**: tables/collections, key columns, relations, indexes, constraints (from migrations/models/schema)
   - **Contracts**: endpoints, commands, jobs, events, webhooks → inputs, outputs, errors, status codes
   - **Key sequences**: mermaid `sequenceDiagram` for the 1–3 most important flows
   - **State machines**: status fields and allowed transitions (mermaid `stateDiagram-v2` if non-trivial)
   - **Business rules and calculations**: validation, pricing, currency, rounding, dates/time zones
   - **Concurrency / idempotency / retries**: locks, unique keys, queue retry settings, duplicate handling
   - **Failure modes**: what happens when each dependency is down or slow
   - **Config / feature flags** (names only), **observability**, **security** (authz, PII), **performance** (N+1, heavy queries, caching)
   - **Known issues / tech debt**
4. Write or replace the module's section in `.ai/lld.md` using the template in that file. Mark inferences `(unverified)`.
5. Add gaps to `.ai/memory/questions.md`, link the module in `.ai/context/map.md`, and summarise the 3 biggest risks.
