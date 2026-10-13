#!/usr/bin/env bash
# SessionStart hook (startup | resume | clear | compact).
# Prints the project brain summary; Claude Code adds this stdout to Claude's context.
# Phrased as facts, not commands, so it reads as project context.

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
AI="$ROOT/.ai"
cat >/dev/null 2>&1   # drain hook JSON on stdin

if [ ! -d "$AI" ]; then
  echo "This repo has no .ai/ project brain yet. The /onboard-repo skill creates it."
  exit 0
fi

echo "=== Project brain (.ai/) — loaded by session-start hook ==="
echo "Rule book: .ai/rules.md · Index: .ai/README.md"

if [ -f "$AI/memory/state.md" ]; then
  echo
  echo "--- .ai/memory/state.md (working memory) ---"
  head -n 80 "$AI/memory/state.md"
fi

if [ -f "$AI/tasks.md" ]; then
  echo
  echo "--- .ai/tasks.md: In progress / Blocked ---"
  awk '/^## /{p=($0 ~ /^## (In progress|Blocked)/)} p' "$AI/tasks.md" | grep -v '^<!--' | head -n 40
fi

if [ -f "$AI/memory/questions.md" ]; then
  n=$(grep -c '^- \[ \]' "$AI/memory/questions.md" 2>/dev/null || true)
  if [ "${n:-0}" -gt 0 ] 2>/dev/null; then
    echo
    echo "Open questions for the human in .ai/memory/questions.md: $n"
  fi
fi

if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo
  echo "--- git ---"
  echo "Branch: $(git -C "$ROOT" branch --show-current 2>/dev/null)"
  changed=$(git -C "$ROOT" status --porcelain 2>/dev/null | grep -v -E '^.. "?\.(ai|claude)/' | wc -l | tr -d ' ')
  echo "Uncommitted changed files outside .ai/ and .claude/: $changed"
  sk="$AI/context/skeleton.md"
  if [ -f "$sk" ]; then
    h=$(sed -n 's/.*Generated at commit: \([0-9a-f]\{7,40\}\).*/\1/p' "$sk" | head -n 1)
    if [ -n "$h" ] && git -C "$ROOT" cat-file -e "$h^{commit}" 2>/dev/null; then
      behind=$(git -C "$ROOT" rev-list --count "$h..HEAD" 2>/dev/null || echo 0)
      if [ "${behind:-0}" -gt 0 ] 2>/dev/null; then
        echo ".ai/context/skeleton.md is $behind commit(s) behind HEAD (refresh-skeleton skill updates it)."
      fi
    fi
  else
    echo ".ai/context/skeleton.md does not exist yet (refresh-skeleton or onboard-repo skill creates it)."
  fi
fi
exit 0
