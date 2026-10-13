# Project brain (`.ai/`)

Persistent, structured memory for AI agents working on this repo. Small files, each with one job.
Agents read `rules.md` first, then `memory/state.md` and `tasks.md`.

| File | Purpose | Pattern |
|---|---|---|
| `rules.md` | Rule book for AI agents: commands, exploration order, question protocol, definition of done | — |
| `prd.md` | Product requirements: what the system must do and for whom | — |
| `architecture.md` | High-level architecture: components, integrations, data stores, deployment shape | — |
| `lld.md` | Low-level design per module: data model, contracts, sequences, edge cases | — |
| `design.md` | UI design system: typography, colours, spacing, components | — |
| `tasks.md` | Roadmap and task board: In progress / Todo / Blocked / Done | — |
| `deployment.md` | Environments, build, release, rollback, env var names | — |
| `testing.md` | Test commands, structure, fixtures, coverage gaps | — |
| `glossary.md` | Business/domain terms and what they map to in code | — |
| `memory/state.md` | Working scratchpad for the current task (keep < 60 lines) | Structured state (pattern 3) |
| `memory/decisions.md` | Decision log (lightweight ADRs) | Persistent memory |
| `memory/questions.md` | Open questions for the human, with answers once resolved | Persistent memory |
| `context/map.md` | Where things live, entry points, links to traced flows | Just-in-time exploration (pattern 4) |
| `context/skeleton.md` | Generated symbol + entry-point map with line numbers | Skeletonization (pattern 1) |
| `context/flows/*.md` | One file per traced business flow | Business logic tracing |
| `review/` | Review packets and second-opinion findings (can be gitignored) | Cross-model review |
