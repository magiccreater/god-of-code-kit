---
name: ops-docs
description: Build or refresh .ai/deployment.md and .ai/testing.md from CI pipelines, Dockerfiles, k8s/terraform, Makefiles, package scripts and test configs, verifying safe commands by running them. Use when asked how to deploy or test this repo, when onboarding, or after build/CI changes.
---

1. Read only what exists: CI files (`.github/workflows/*`, `.gitlab-ci.yml`, `bitbucket-pipelines.yml`, `azure-pipelines.yml`), `Dockerfile*`, `docker-compose*`, `k8s/`, `helm/`, `terraform/`, `Makefile`, `package.json` scripts, `composer.json` scripts, `phpunit.xml`, `jest/vitest/playwright` configs, `.env.example` (names only).
2. **testing.md** — commands (all / one file / one test / coverage), test layout, factories/seeders/fixtures, what is mocked, CI test stages, coverage gaps, flaky tests. **Run** the unit test command (and a single-test command) to verify; record the date, command and result.
3. **deployment.md** — environments, build steps, pipeline stages and gates, release steps, migrations and rollback, feature flags, env var names and where they are set, workers/schedulers/queues, post-deploy checks. Never run deploy, migrate or infra-apply commands; document them only.
4. Update the commands table in `.ai/rules.md` §0 to match.
5. Mark anything not verified `(unverified)` and put gaps in `.ai/memory/questions.md`.
6. If `/run` and `/verify` do not yet know how to launch the app, suggest `/run-skill-generator`.
