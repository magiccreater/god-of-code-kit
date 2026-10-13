# God of Code kit

A per-repo setup that turns **Claude Code (Opus 5.5)** + **Antigravity CLI (Gemini Pro)** into one disciplined coding system:
understands new repos, traces business logic, writes and changes code test-first, keeps a living project brain
(`.ai/`), asks when context is missing, writes LLD / deployment / testing docs, and gets cross-model reviews.

## 1. Who does what

| Role | Tool + model | Why |
|---|---|---|
| **Driver**: explore, plan, implement, refactor, debug | Claude Code with **Opus 5.5** | Strongest coder of the two; skills, hooks, subagents, plan mode |
| **Fresh-eyes reviewer** (same family) | `code-reviewer` subagent (Opus, read-only, clean context) | Catches what the author missed; runs on every non-trivial diff |
| **Cross-model reviewer** (different family) | Antigravity CLI `agy` with **Gemini Pro** via `/second-opinion` | Different training → different blind spots. Use on payments, auth, finance, migrations, concurrency |
| **Big-context sweeps and fallback** | `agy` with Gemini Pro | Whole-module reading when you hit Claude limits, or when Claude is unavailable |
| **Shared memory for both** | `.ai/` folder + `AGENTS.md` / `GEMINI.md` | Both agents read the same rules, state and docs, so you can switch mid-task |

## 2. What gets installed into a repo

```
AGENTS.md            → imports .ai/rules.md (read by Claude Code and most agents)
CLAUDE.md            → imports AGENTS.md + Claude-specific notes
GEMINI.md            → tells Gemini/Antigravity to read the same rules; default role = reviewer
.ai/                 → the project brain (one folder per project, updated as you work)
  rules.md             rule book: commands, JIT exploration order, question protocol, definition of done
  prd.md architecture.md lld.md design.md deployment.md testing.md glossary.md
  tasks.md             board: In progress / Blocked / Todo / Done
  memory/state.md      working scratchpad (structured state, pattern 3)
  memory/decisions.md  decision log (ADRs)
  memory/questions.md  open questions for you
  context/map.md       where things live + entry points (JIT exploration, pattern 4)
  context/skeleton.md  generated symbol/route map with line numbers (skeletonization, pattern 1)
  context/flows/       one file per traced business flow
  review/              review packets + Gemini findings (gitignored)
.claude/
  skills/              onboard-repo, refresh-skeleton, trace-flow, start-task, sync-brain, write-lld, ops-docs, second-opinion
  agents/code-reviewer.md
  god/hooks/           session_start.sh (loads the brain), stop_check.sh (forces brain updates)
  settings.json        hooks, Opus as default model, deny rules for .env and force-push
```

## 3. One-time setup per machine

1. **Claude Code**: install it and log in with your Claude subscription (docs: https://code.claude.com/docs). In a session, run `/model` and pick Opus 5.5.
2. **Antigravity CLI** (`agy`): install it and sign in with the Google account that has Google AI Pro. Gemini CLI was retired for AI Pro users on 18 June 2026; `agy` replaced it and can import old Gemini CLI settings on first run.
3. Put this kit in **your own GitHub repo** (e.g. `god-of-code-kit`) so every machine and Codespace can `git clone` it.
4. Windows: run the installer from Git Bash (or WSL). Hooks call `bash`, so Git's `bash.exe` must be on PATH; if hooks fail, run Claude Code inside WSL.

## 4. Install into a project

```bash
git clone https://github.com/<you>/god-of-code-kit ~/god-of-code-kit
~/god-of-code-kit/install.sh ~/code/my-repo              # shared: commit it, works on web/phone too
~/god-of-code-kit/install.sh ~/code/client-repo --private  # private: nothing committed (client/employer code)
```

Re-running upgrades skills/hooks and never overwrites what's already in `.ai/`. An existing `model` setting is kept, so check `/model`.

**Private mode** writes `CLAUDE.local.md` and `.claude/settings.local.json` and hides all kit files with `.git/info/exclude`. Trade-off: cloud sessions (claude.ai/code on your phone) clone from GitHub and will not see private-mode files.

## 5. Daily workflow

| When | Run |
|---|---|
| First time in a repo | `/onboard-repo` → reads skeleton + manifests, fills `.ai/`, asks you the top questions |
| Before touching business logic | `/trace-flow booking checkout` → `.ai/context/flows/booking-checkout.md` with file:line sources + sequence diagram |
| Any feature / change / bug | `/start-task <description>` → clarify → impact analysis → plan → tests first → implement → verify → reviewer subagent → brain update |
| Module design | `/write-lld payments` |
| Deploy / test knowledge | `/ops-docs`, then `/run-skill-generator` once so `/run` and `/verify` can launch the app |
| Risky diff | `/second-opinion current diff` → Gemini reviews from a packet in `.ai/review/` |
| End of session / before `/compact` | `/sync-brain` (the stop hook also nudges you automatically) |

Built-in Claude Code commands worth using alongside: plan mode, `/code-review`, `/security-review`, `/debug`, `/verify`, `/compact`, `/context`.

**Switching to Gemini mid-task** (Claude limit hit): open `agy` in the repo and say *"Read AGENTS.md, .ai/memory/state.md and .ai/tasks.md, then continue the In-progress task following .ai/rules.md."*

## 6. Coding from anywhere

| Device | How |
|---|---|
| Laptop / desktop | Claude Code in terminal, VS Code or desktop app; `agy` in a second terminal |
| Phone / tablet | Claude Code on the web (claude.ai/code) on your GitHub repo — uses the committed `.claude/` and `.ai/` (shared mode). For Gemini, run `agy` in a GitHub Codespace from the phone browser |
| Anything else | Remote Control into a running Claude Code session on your laptop |

## 7. How the hooks work

- **SessionStart** (`startup|resume|clear|compact`): prints `state.md`, In-progress/Blocked tasks, open-question count, git branch, and warns if `skeleton.md` is behind HEAD. After auto-compaction it reloads the same, so the agent never loses the thread.
- **Stop**: if code files changed after `state.md` was last updated, it blocks once per prompt and asks the agent to update `state.md` and `tasks.md`. It never loops. Remove the `Stop` entry from settings to turn it off.

## 8. Limits to know

- No setup makes a model "never wrong". The gains come from discipline: tests as the judge, a fresh reviewer, a cross-model reviewer, and memory that survives sessions.
- `skeleton.py` is regex-based and approximate (PHP, TS/JS, Python, Go, Java/Kotlin, C#, Ruby; Laravel/Express/Nest/Flask routes, Next.js pages, Laravel schedules/jobs/commands). One-line class bodies are only partly mapped.
- `/second-opinion` only runs `agy` automatically if `agy --help` shows a non-interactive prompt flag; otherwise it gives you the exact prompt to paste.
- Antigravity's Pro quota refreshes on a rolling window under a weekly cap, and users have reported multi-day lockouts, so keep Gemini for review and fallback rather than as the main driver.
