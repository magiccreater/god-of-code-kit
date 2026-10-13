#!/usr/bin/env bash
# PreToolUse hook used only while the qa-skeptic subagent runs: file writes are allowed only inside
# .ai/review/ (its scratch worktrees and reports). Anything else is denied, so QA can never edit your code.
input=$(cat 2>/dev/null)
field() { printf '%s' "$input" | sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" | head -n 1; }
path=$(field file_path)
[ -n "$path" ] || path=$(field notebook_path)
path=$(printf '%s' "$path" | sed 's#\\\\#/#g')
case "$path" in
  *..*) ;;                                   # never allow path traversal
  */.ai/review/*|.ai/review/*) exit 0 ;;
esac
printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"qa-skeptic may only write inside .ai/review/ (its scratch worktree). Report the change instead of editing project files."}}'
exit 0
