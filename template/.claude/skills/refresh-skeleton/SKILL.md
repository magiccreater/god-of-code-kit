---
name: refresh-skeleton
description: Regenerate .ai/context/skeleton.md, the compact map of classes, functions, routes and entry points with line numbers. Use when skeleton.md is missing or behind HEAD, or after files or classes were added, moved or renamed.
allowed-tools:
  - Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/skeleton.py *)
  - Bash(python ${CLAUDE_SKILL_DIR}/scripts/skeleton.py *)
---

Run the generator (use `python` instead of `python3` on Windows):

```
python3 ${CLAUDE_SKILL_DIR}/scripts/skeleton.py ${CLAUDE_PROJECT_DIR}
```

Optional flags: `--max-chars 80000` for a bigger map, `--out <path>`, `--include <dir>` (repeatable) to map only part of a monorepo, `--engine auto|regex|tree-sitter`.

The default engine (`auto`) uses tree-sitter when `tree-sitter-language-pack` is installed (more accurate: multi-line signatures, one-line class bodies, constructors) and the built-in regex rules otherwise. If the script crashes or hangs with tree-sitter, rerun with `--engine regex`.

Then read only the top of `.ai/context/skeleton.md` (entry points and directory overview) and report in two or three lines: file count, main areas, anything surprising. Do not read the whole skeleton unless the current task needs it — search it with grep instead.
