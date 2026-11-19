# God of Code kit

For WSL-isolated coding and Codex review through AWS or Oracle, see the [WSL quick start](WSL.md). After setup, run `god task "your change" --single` from a target Git repository. See the [kit task board](.ai/tasks.md) for completed work and the next coding milestones.

A per-repo setup that turns **Claude Code (Opus 5.5)** + **Antigravity CLI (Gemini Pro)** into one disciplined coding system:
understands new repos, traces business logic, writes and changes code test-first, keeps a living project brain
(`.ai/`), asks when context is missing, writes LLD / deployment / testing docs, and gets cross-model reviews.

## 1. Who does what

| Role | Tool + model | Why |
|---|---|---|
| **Driver**: explore, plan, implement, refactor, debug | Claude Code with **Opus 5.5** | Strongest coder of the two; skills, hooks, subagents, plan mode |
| **Fresh-eyes reviewer** (same family) | `code-reviewer` subagent (Opus, read-only, clean context) | Catches what the author missed; runs on every non-trivial diff |
| **Skeptical QA** | `qa-skeptic` subagent in a scratch git worktree | Proves the new test fails before the fix and passes after, checks regressions, writes edge-case tests to break the change. Bug fixes and risky changes |
| **Cross-model reviewer** (different family) | Antigravity CLI `agy` with **Gemini Pro** via `/second-opinion` | Different training → different blind spots. Use on payments, auth, finance, migrations, concurrency |
| **Big-context sweeps and fallback** | `agy` with Gemini Pro | Whole-module reading when you hit Claude limits, or when Claude is unavailable |
| **Shared memory for both** | `.ai/` folder + `AGENTS.md` / `GEMINI.md` | Both agents read the same rules, state and docs, so you can switch mid-task |

## 2. What gets installed into a repo

```
AGENTS.md            → imports .ai/rules.md (read by Claude Code and most agents)
CLAUDE.md            → imports AGENTS.md + Claude-specific notes
GEMINI.md            → tells Gemini/Antigravity to read the same rules; default role = reviewer
.ai/                 → the project brain (one folder per project, updated as you work)
  rules.md             rule book: §0 your commands/rules; §1-9 kit rules (exploration order, two-failure rule,
                       quiet tests, question protocol, definition of done)
  prd.md architecture.md lld.md design.md deployment.md testing.md glossary.md
  tasks.md             board: In progress / Blocked / Todo / Done
  specs/<T-id>/spec.md one spec per task: why, what, acceptance criteria (AC-001…), bug repro steps, convergence
  readiness.json       when a task counts as ready to start (advisory by default, ready at 80/100)
  memory/state.md      working scratchpad (structured state, pattern 3)
  memory/decisions.md  decision log (ADRs)
  memory/questions.md  open questions for you
  context/map.md       where things live + entry points (JIT exploration, pattern 4)
  context/skeleton.md  generated symbol/route map with line numbers (skeletonization, pattern 1)
  context/flows/       one file per traced business flow
  review/              review packets + Gemini findings (gitignored)
.claude/
  skills/              onboard-repo, refresh-skeleton, trace-flow, task-ready, start-task, converge, sync-brain,
                       write-lld, ops-docs, second-opinion, ready-gate
  agents/              code-reviewer.md (read-only review), qa-skeptic.md (adversarial QA in a worktree)
  god/hooks/           session_start.sh (loads the brain), stop_check.sh (forces brain updates),
                       pretool_guard (protects existing tests, nudges test-less commits, enforces
                       readiness and the decision gate in required mode),
                       qa_write_guard.sh (QA may only write in .ai/review/)
  god/qa_worktree.sh   scratch worktrees for QA: create / add-file / apply / remove / cleanup
  god/decide/          readiness.py (is the task ready to start?), decision_gate.py (is the change ready
                       to ship?), vega_server.py (vegaml over HTTP)
  god/manifest.json    hashes of the kit files last installed (so upgrades keep the ones you edited)
.ai/decision-gate.json decision gate config: mode, checks, model server, questions, thresholds (off by default)
  settings.json        hooks, Opus as default model, deny rules for .env and force-push
```

## 3. One-time setup per machine

1. **Claude Code**: install it and log in with your Claude subscription (docs: https://code.claude.com/docs). In a session, run `/model` and pick Opus 5.5.
2. **Antigravity CLI** (`agy`): install it and sign in with the Google account that has Google AI Pro. Gemini CLI was retired for AI Pro users on 18 June 2026; `agy` replaced it and can import old Gemini CLI settings on first run.
3. Put this kit in **your own GitHub repo** (e.g. `god-of-code-kit`) so every machine and Codespace can `git clone` it.
4. Windows: run the installer from Git Bash (or WSL). Hooks call `bash`, so Git's `bash.exe` must be on PATH; if hooks fail, run Claude Code inside WSL.
5. Python 3.8+ is required (installer, test guard, skeleton). Optional, for more accurate skeleton maps: `pip install tree-sitter-language-pack` (grammars download on first use).

## 4. Install into a project

```bash
git clone https://github.com/<you>/god-of-code-kit ~/god-of-code-kit
~/god-of-code-kit/install.sh ~/code/my-repo              # shared: commit it, works on web/phone too
~/god-of-code-kit/install.sh ~/code/client-repo --private  # private: nothing committed (client/employer code)
```

**Upgrading:** `git pull` the kit, then re-run the same install command. Skills, agents and hooks are upgraded unless you edited them: an edited file is kept and the new version is written next to it as `<file>.kit-new` for you to merge (delete the `.kit-new` afterwards, or make your file identical and the next run removes it). "Edited" means it matches neither what the installer last put there (`.claude/god/manifest.json`) nor any version the kit ever shipped (`kit/shipped.sha256`); in `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` and `.ai/rules.md` only the part between `<!-- god-of-code ... begin/end -->` markers is replaced, so your own text (and `rules.md` section 0) is kept. Everything else in `.ai/` is never overwritten. An existing `model` setting is kept, so check `/model`. Repos installed before markers existed get `.ai/rules.md.kit-new` to merge once.

**Private mode** writes `CLAUDE.local.md` and `.claude/settings.local.json` and hides all kit files with `.git/info/exclude`. Trade-off: cloud sessions (claude.ai/code on your phone) clone from GitHub and will not see private-mode files.

## 5. Daily workflow

| When | Run |
|---|---|
| First time in a repo | `/onboard-repo` → reads skeleton + manifests, fills `.ai/`, asks you the top questions |
| Before touching business logic | `/trace-flow booking checkout` → `.ai/context/flows/booking-checkout.md` with file:line sources + sequence diagram |
| A new ticket or bug report | `/task-ready <description>` → `.ai/specs/T-###/spec.md`, a readiness score and only the questions whose answers are missing (section 8) |
| Any feature / change / bug | `/start-task <description>` → task-ready → impact analysis → plan → new tests first → implement → verify → `/converge` (every AC has a named test) → `code-reviewer` (+ `qa-skeptic` for fixes/risky work) → brain update |
| Check a fix properly | ask Claude to "use the qa-skeptic agent on this change" → fail-before / pass-after / regressions / adversarial tests report |
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
- **PreToolUse (test guard)**: before Edit/Write or a shell command (`sed -i`, `>`, `rm`, `mv`, `git checkout/restore/rm` …) touches a test file that already exists in HEAD, you get an approval prompt. New test files are never blocked. Before a `git commit` (including `-a`) that changes source but no tests, you get an approval prompt too. It asks, never refuses, and does nothing outside git repos.
- **PreToolUse (task readiness)**: only in readiness `required` mode, edits to source files (not tests, docs, `.ai/` or `.claude/`) are **denied** until the *Current task* in `state.md` has a fresh `ready` check, so the spec can still be completed. Editing `.ai/readiness.json` or a readiness record asks first in every mode.
- **PreToolUse (decision gate)**: only in decision-gate `required` mode, `git push` and `gh pr create/merge` are **denied** without a fresh `ready` receipt (section 9). Editing `.ai/decision-gate.json` asks first in every mode.
- **qa-skeptic only**: while that subagent runs, writes outside `.ai/review/` are denied.

The two-failure rule, quiet test commands and batched searches are rules in `.ai/rules.md`, not hooks: they need judgment, and a hook that hard-resets or truncates would destroy your uncommitted work or the failing assertion.

## 8. Task readiness

Most bad changes start from a thin ticket: no reason, no acceptance criteria, a bug with no steps to reproduce. `/task-ready` turns the request into `.ai/specs/T-###/spec.md`, scores it, and asks only for what is missing before any code is written.

```bash
python .claude/god/decide/readiness.py new T-031 --type bug --title "Double charge on Pay" --risk high
python .claude/god/decide/readiness.py check T-031    # score, missing items, at most 5 questions, record
python .claude/god/decide/readiness.py trace T-031    # which acceptance criteria a test names
python .claude/god/decide/readiness.py status         # mode, current task, is its check still fresh?
```

| Type | Must have | Should have |
|---|---|---|
| `feature` | why, what, testable acceptance criteria | each FR-xxx covered by an AC, out of scope, edge cases, non-functional, dependencies/access |
| `bug` | why, steps to reproduce (2+ numbered), expected, actual (≠ expected), environment/version | evidence (exact error, log, trace), impact, acceptance criteria |
| `change` | why, what, what must not change, acceptance criteria | FR coverage, out of scope, edge cases |
| `refactor` | why, what, what must not change, existing tests (safety net), acceptance criteria | — |
| `chore` | why, what | — |

`risk: high` (payments, money, auth, migrations, concurrency) adds a rollback plan (must) and reviewers (should). Any open `[NEEDS CLARIFICATION: …]` blocks ready.

| Rule | What it means |
|---|---|
| Scoring | Each item is ok (full weight), weak (half) or missing. Placeholders (`TODO`, `TBD`, `...`) and the template's hint comments count as empty; "none" is a fine answer for scope, edge cases, non-functional and dependencies. |
| Quality, not just presence | An acceptance criterion must be Given/When/Then or name an observable result (a number, a quoted value, "returns", "is rejected"…); "fast", "user-friendly", "works correctly" with nothing measurable is weak. Bug steps must be numbered actions; actual must differ from expected. |
| Verdicts | `ready`: score ≥ 80 and every must-have ok. `needs_info`: answer the questions (at most 5) and check again. `not_ready`: under 50, the ticket needs rewriting. |
| Modes | `advisory` (default) scores and asks, never blocks. `required`: the hook denies source edits until the current task is ready. `off`. |
| Records | `.ai/review/readiness/<T-id>.json`, bound to the spec's and config's SHA-256: edit the spec and the record is stale. |
| Optional model | `"model": {"enabled": true}` also asks the decision-gate model whether the criteria cover the goal (or whether the bug can be reproduced). It can only lower a verdict, and remote models are refused in private repos. |
| Project tweaks | `skip` drops an item with a reason, e.g. `{"reviewers": "solo project"}`. |

**Acceptance criteria drive the rest.** Write them as `- AC-001 (FR-001): Given … When … Then …` and name each test after its criterion (`test_ac_001_…`, `it("AC-001 …")`). After implementing, `/converge` checks the code against the spec and appends any gaps as new tasks. The decision gate uses the spec's title, why and criteria as the goal, and an acceptance criterion that no test names caps its verdict at `needs_review`. `qa-skeptic` reproduces bugs from the spec's steps, or reports "could not reproduce".

## 9. Decision gate (optional)

A fast typed-decision model (Laya, vegaml or TypeSafe Jev) gives a calibrated "is this change ready?" opinion **after** the deterministic checks pass. It asks four yes/no questions about the diff: high-risk area, unfinished work, unrelated changes, complete for the goal. Off by default.

```bash
python .claude/god/decide/decision_gate.py check    # or the /ready-gate skill
python .claude/god/decide/decision_gate.py status   # mode, server, privacy, latest receipt
python .claude/god/decide/decision_gate.py verify   # does the latest receipt still match the code?
```

| Rule | What it means |
|---|---|
| Checks first | Commands in `checks` run in order; if one fails the verdict is `not_ready` and the model is never asked. No checks configured → never `ready`. |
| Unsure = not ready | Abstention, several plausible answers, confidence below `min_confidence`, timeout, malformed or non-finite output, an unexpected model, or a truncated diff → `needs_review` / `unavailable`. |
| Modes | `off` does nothing. `advisory` reports and never blocks. `required`: anything but `ready` exits 1, and the hook **denies** `git push` / `gh pr create` without a fresh `ready` receipt. |
| Receipts | `.ai/review/receipts/` (gitignored). Bound to base commit + exact diff (incl. untracked files) + config + reported model. Any change → stale. Committing the same content keeps it fresh; editing `.ai/` doesn't count. |
| No surprise downloads | The gate only makes one HTTP call. Model setup and pinning happen in the model server. |
| Privacy | Secret-looking values and files like `.env*`, `*.pem` are withheld from the model. Remote endpoints (e.g. Jev) are **refused in private-mode repos**. |
| Tamper check | Editing `.ai/decision-gate.json` (by Edit/Write or shell) asks you first. |

**Pick a model server** (all speak `POST /v1/systemone`; set `provider.url` in `.ai/decision-gate.json`):

| Server | Start it | Notes |
|---|---|---|
| Laya (local) | `pip install "laya[serve]"` then `laya-serve` (port 8000) | Apache-2.0 weights. Base checkpoints are weak on new tasks until fine-tuned. |
| vegaml (local) | `pip install vegaml`, `python .claude/god/decide/vega_server.py setup` once, then `... serve` (port 8765) | Setup pins a revision and hashes every file; serve runs offline and refuses mismatched files. Adds abstain / prediction-set / unbound signals. Weights licence not stated on Hugging Face. |
| TypeSafe Jev (hosted) | `provider.url = https://api.typesafe.ai`, key in `$DECISION_GATE_API_KEY`, `provider.model` and `expected_model` = e.g. `jev-1.13.0` | Your diff leaves the machine: shared repos only. |

Speed on a laptop CPU is unmeasured; time `check` before relying on it.

**Before using required mode, measure it on your own history.** None of these models was trained on code-review decisions. Label 50–200 past diffs (JSONL, one per line):

```json
{"goal": "Fix rounding in refunds", "diff": "<output of git show <sha>>", "labels": {"high_risk": true, "unfinished": false, "complete": true}}
```

`decision_gate.py calibrate --data labelled.jsonl` prints accuracy, Brier score, calibration error, unsure rate and **missed failures** (real problems the gate would have passed confidently). Aim for zero missed failures; otherwise raise `min_confidence` or tighten `pass_when`.

## 10. Limits to know

- Task readiness checks that the information is there and is specific; it cannot tell whether the requirement is the right one. That is still your call.
- `trace` matches criterion ids (`AC-001`, `ac_1`, `ac-001`) in test files; it does not prove the test asserts the right thing. `/converge` and `qa-skeptic` look at that.
- No setup makes a model "never wrong". The gains come from discipline: tests as the judge, a fresh reviewer, a cross-model reviewer, and memory that survives sessions.
- `skeleton.py` covers PHP, TS/JS, Python, Go, Java/Kotlin, C#, Ruby, Rust and C/C++, plus Laravel/Express/Nest/Flask/actix/axum routes, Next.js pages, Laravel schedules/jobs/commands and `main` functions. Without tree-sitter it is regex-based: multi-line signatures and one-line class bodies are only partly mapped. With tree-sitter installed it parses properly; if that ever crashes, use `--engine regex`.
- The test guard recognises tests by folder (`tests/`, `__tests__/`, `spec/` …) and name (`*_test.go`, `*.spec.ts`, `FooTest.php` …). Rust unit tests inside `src/` files (`#[cfg(test)]`) are not seen as tests, so a commit that only adds such tests still gets the "no tests" prompt — just approve it.
- `qa-skeptic` links `vendor/`, `node_modules/` and virtualenvs into its worktree and copies env files, but tests that need a database, Docker or other services may not run there; it then says so and verifies in your working tree read-only.
- `/second-opinion` only runs `agy` automatically if `agy --help` shows a non-interactive prompt flag; otherwise it gives you the exact prompt to paste.
- Antigravity's Pro quota refreshes on a rolling window under a weekly cap, and users have reported multi-day lockouts, so keep Gemini for review and fallback rather than as the main driver.
