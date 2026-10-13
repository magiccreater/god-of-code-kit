---
name: onboard-repo
description: Understand a new or unfamiliar repository and build its project brain in .ai/ (map, architecture, commands, testing and deployment drafts, glossary, open questions). Use when starting work on a repo for the first time or when .ai/ is mostly empty.
effort: high
---

Goal: after this skill, any agent can work in the repo by reading `.ai/` instead of re-exploring. Work cheaply: skeleton and manifests first, line ranges only, no full-directory reads.

1. **Skeleton** — run the refresh-skeleton skill. Read its entry-point and overview sections.
2. **Manifests and config** — read only what exists of: `README*`, `composer.json`, `package.json`, `pyproject.toml`/`requirements*.txt`, `go.mod`, `Dockerfile*`, `docker-compose*`, `Makefile`, CI files (`.github/workflows/*`, `.gitlab-ci.yml`, `bitbucket-pipelines.yml`), k8s/helm/terraform folders, `phpunit.xml`, `jest/vitest/playwright` configs, `.env.example` (names only). Never open real `.env` files.
3. **Commands** — fill the table in `.ai/rules.md` section 0. Verify safe ones by running them (install is optional; run the unit test command if it is cheap). Record results in `.ai/testing.md`.
4. **Architecture** — write `.ai/architecture.md`: stack and versions, components, data stores, integrations, hosting. Include one mermaid flowchart. Cite files.
5. **Map** — write `.ai/context/map.md`: entry points (routes files, commands, jobs, schedulers, webhooks, pages), a "where things live" table, hotspots/gotchas you noticed.
6. **Ops drafts** — draft `.ai/deployment.md` and `.ai/testing.md` from CI and config. Mark anything not verified `(unverified)`.
7. **Glossary** — seed `.ai/glossary.md` with the main domain nouns (model/entity names, status values) and where they live.
8. **Product guess** — draft `.ai/prd.md` from what the code does; mark it `(inferred from code — confirm)`.
9. **Questions** — put every gap in `.ai/memory/questions.md`. Ask the human the top 1–4 questions that most change understanding (question protocol in rules.md).
10. **Wrap up** — update `.ai/memory/state.md` (goal: onboarding done; next action), add follow-up tasks to `.ai/tasks.md` Todo (e.g. "trace <main business flow>"), and report: what the system is, main flows to trace next, open questions.

For large repos (> ~2,000 files) delegate wide searches to read-only Explore subagents and keep only their conclusions. Suggest running `/run-skill-generator` once so `/run` and `/verify` know how to launch the app.
