---
name: trace-flow
description: Trace one business flow end to end (from route, command, job, webhook or UI action through services, data and side effects) and document it in .ai/context/flows/. Use when asked how something works, before changing business logic, or when debugging behaviour across several files.
argument-hint: "[flow name or entry point, e.g. 'booking checkout' or 'POST /api/bookings']"
effort: high
---

Flow to trace: $ARGUMENTS

1. **Check existing knowledge** — look in `.ai/context/map.md` and `.ai/context/flows/`. If the flow is documented, verify it against current code (spot-check the cited lines) and update instead of rewriting.
2. **Find the entry point** — grep `.ai/context/skeleton.md` for routes/commands/jobs matching the flow; confirm in code. If several candidates exist and the choice matters, ask.
3. **Follow the calls depth-first**, reading only the relevant line ranges. For each hop note `file:line`. Stop descending into framework/library internals; note them as boundaries.
4. **Capture**, with sources for every item:
   - Trigger and inputs (who/what starts it, payload, auth)
   - Numbered step sequence (`Class::method` @ `path:line`)
   - Data read / written (tables, columns, cache keys) and transactions
   - External calls (gateways, ERP, email/SMS, queues) and what happens if they fail or time out
   - Business rules: validations, calculations, status transitions, currency/rounding, dates/time zones
   - Side effects: events, queued jobs, notifications, logs
   - Error paths and retries/idempotency
   - Tests that cover the flow, and gaps
5. **Write** `.ai/context/flows/<kebab-slug>.md` with sections in that order, plus one mermaid `sequenceDiagram`. Mark anything inferred `(unverified)`.
6. **Link** it from `.ai/context/map.md` (Traced flows), add new terms to `.ai/glossary.md`, and put open points in `.ai/memory/questions.md`.
7. **Report** a 5–8 line summary of the flow and the riskiest parts.
