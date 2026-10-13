# Deployment

Env var **names** only — never values.

- **Environments**: local / staging / production → URLs, hosting
- **Build**: commands, Dockerfile(s), artifacts
- **CI/CD**: pipeline file(s), stages, required checks, who approves
- **Release steps**: (numbered)
- **Database migrations**: how and when they run, rollback strategy
- **Feature flags**:
- **Rollback**: exact steps; rollback triggers
- **Environment variables**: name → purpose → where set
- **Scheduled jobs / queues / workers**: what runs where
- **Monitoring after deploy**: dashboards, logs, alerts to watch
- **Last verified**: (date, by whom, how)
