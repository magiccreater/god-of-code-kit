---
name: ready-gate
description: Run the decision gate - the project's deterministic checks first, then a fast typed-decision model (laya-serve, vega_server.py or Jev) asks whether the change is high-risk, unfinished, off-scope or incomplete - and record a receipt. Use before calling a task done or before pushing, when .ai/decision-gate.json mode is advisory or required.
argument-hint: "[optional task goal]"
allowed-tools:
  - Bash(python3 .claude/god/decide/decision_gate.py *)
  - Bash(python .claude/god/decide/decision_gate.py *)
---

Goal override: $ARGUMENTS

1. Run (use `python` instead of `python3` on Windows):

   ```
   python3 .claude/god/decide/decision_gate.py check
   ```

   Add `--goal "<goal>"` if the user gave one above or `.ai/memory/state.md` has no Goal line.

2. Act on the verdict:
   - **OFF** — say the gate is off and how to switch it on (`mode` in `.ai/decision-gate.json`). Nothing else.
   - **NOT_READY** — a deterministic check failed or nothing changed. Fix that first; the model was not asked.
   - **NEEDS_REVIEW** — follow every line under "Next". High risk → `qa-skeptic` agent (plus `/second-opinion` for payments, auth or migrations). Unsure answers → review those areas yourself and tell the human. Then fix and re-run.
   - **UNAVAILABLE** — the model server is down, timed out, answered as an unexpected model, or was refused (remote model, private repo). Report it; do not retry in a loop. In required mode the change cannot be published until it is resolved.
   - **READY** — report it with the receipt path. It is one signal, not proof: the checks and reviews still stand.

3. Never edit `.ai/decision-gate.json` to make a verdict pass (lowering thresholds, removing checks or questions, switching mode). Propose such changes to the human instead.

4. Add the verdict and receipt path to `.ai/memory/state.md`.

`decision_gate.py verify` tells whether the latest receipt still matches the code; `status` shows mode, server reachability and privacy; `calibrate --data labelled.jsonl` measures the model on labelled past diffs (see README).
