#!/usr/bin/env bash
# Stop hook: if code changed after .ai/memory/state.md was last updated, ask Claude
# (once per prompt) to update the project brain before finishing the turn.
# Disable by removing the Stop entry from .claude/settings(.local).json.

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
STATE="$ROOT/.ai/memory/state.md"
input=$(cat 2>/dev/null)

[ -f "$STATE" ] || exit 0
git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

field() { printf '%s' "$input" | sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" | head -n 1; }
sid=$(field session_id)
pid=$(field prompt_id)
key=$(printf '%s-%s' "${sid:-nosession}" "${pid:-noprompt}" | tr -c 'A-Za-z0-9-' '_')
marker="${TMPDIR:-/tmp}/god-of-code-stop-$key"
[ -e "$marker" ] && exit 0   # already reminded for this prompt: never loop

newer=$(
  cd "$ROOT" || exit 0
  git status --porcelain --untracked-files=all 2>/dev/null \
    | cut -c4- | sed 's/.* -> //; s/^"//; s/"$//' \
    | grep -v -E '^\.(ai|claude)/' \
    | while IFS= read -r f; do
        if [ -f "$f" ] && [ "$f" -nt "$STATE" ]; then printf '%s\n' "$f"; fi
      done | head -n 8
)
[ -z "$newer" ] && exit 0

touch "$marker" 2>/dev/null
list=$(printf '%s' "$newer" | tr '\n' ',' | sed 's/,$//; s/,/, /g')
reason="Code changed after .ai/memory/state.md was last updated (${list}). Before finishing, update .ai/memory/state.md and the task status in .ai/tasks.md (sync-brain skill). If this turn was exploration only, a one-line state update is enough."
esc=$(printf '%s' "$reason" | sed 's/\\/\\\\/g; s/"/\\"/g')
printf '{"decision":"block","reason":"%s"}\n' "$esc"
exit 0
