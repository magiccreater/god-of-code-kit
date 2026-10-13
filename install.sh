#!/usr/bin/env bash
# God of Code kit installer.
#   ./install.sh <repo-path>             shared mode: brain + agent config are committed with the repo
#                                        (works in Claude Code on the web / phone, and for teammates)
#   ./install.sh <repo-path> --private   private mode: nothing is committed; all kit files are excluded
#                                        locally via .git/info/exclude (for client/employer repos)
# Safe to re-run: kit files (skills, agent, hooks) are upgraded; .ai/ knowledge is never overwritten.
set -euo pipefail

KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$KIT/template"
usage() { sed -n '2,7p' "$0"; exit 1; }
[ $# -ge 1 ] || usage
[ -d "$1" ] || { echo "Not a directory: $1"; exit 1; }
REPO="$(cd "$1" && pwd)"; shift
MODE=shared
for a in "$@"; do
  case "$a" in
    --private) MODE=private ;;
    *) usage ;;
  esac
done
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "python3 (or python) is required"; exit 1; }

say() { printf '  %-7s %s\n' "$1" "$2"; }
rel() { printf '%s' "${1#"$REPO"/}"; }

echo "Installing God of Code kit into $REPO ($MODE mode)"

# 1. Project brain: copy templates only where nothing exists yet.
echo "Project brain (.ai/):"
while IFS= read -r -d '' src; do
  dst="$REPO/${src#"$T"/}"
  if [ -e "$dst" ]; then
    say keep "$(rel "$dst")"
  else
    mkdir -p "$(dirname "$dst")"; cp "$src" "$dst"; say add "$(rel "$dst")"
  fi
done < <(find "$T/.ai" -type f -print0)

# 2. Kit-owned files: always installed/upgraded.
echo "Skills, reviewer agent, hooks (.claude/):"
for d in skills agents god; do
  while IFS= read -r -d '' src; do
    dst="$REPO/${src#"$T"/}"
    mkdir -p "$(dirname "$dst")"; cp "$src" "$dst"; say install "$(rel "$dst")"
  done < <(find "$T/.claude/$d" -type f -print0)
done
chmod +x "$REPO/.claude/god/hooks/"*.sh "$REPO/.claude/skills/refresh-skeleton/scripts/skeleton.py" 2>/dev/null || true

# 3. Instruction files.
BEGIN="<!-- god-of-code:begin -->"; END="<!-- god-of-code:end -->"
append_block() {  # file, block-text
  local f="$1" body="$2"
  if [ -f "$f" ] && grep -qF "$BEGIN" "$f"; then say keep "$(rel "$f") (kit block present)"; return; fi
  { [ -s "$f" ] && printf '\n'; printf '%s\n%s\n%s\n' "$BEGIN" "$body" "$END"; } >> "$f"
  say update "$(rel "$f")"
}
CLAUDE_BLOCK="$(sed '1d' "$T/CLAUDE.md")"   # template minus its first line (@AGENTS.md)
echo "Instruction files:"
if [ "$MODE" = shared ]; then
  if [ -f "$REPO/AGENTS.md" ]; then
    append_block "$REPO/AGENTS.md" "$(sed '1,2d' "$T/AGENTS.md")"
  else cp "$T/AGENTS.md" "$REPO/AGENTS.md"; say add AGENTS.md; fi
  if [ -f "$REPO/CLAUDE.md" ]; then
    # An existing CLAUDE.md means Claude Code will not read AGENTS.md by default: import the rule book directly.
    append_block "$REPO/CLAUDE.md" "@.ai/rules.md
$CLAUDE_BLOCK"
  else cp "$T/CLAUDE.md" "$REPO/CLAUDE.md"; say add CLAUDE.md; fi
  if [ -f "$REPO/GEMINI.md" ]; then
    append_block "$REPO/GEMINI.md" "$(sed '1,2d' "$T/GEMINI.md")"
  else cp "$T/GEMINI.md" "$REPO/GEMINI.md"; say add GEMINI.md; fi
  SETTINGS="$REPO/.claude/settings.json"
else
  append_block "$REPO/CLAUDE.local.md" "@.ai/rules.md
$CLAUDE_BLOCK"
  SETTINGS="$REPO/.claude/settings.local.json"
fi

# 4. Settings: merge hooks + permissions + model without clobbering.
"$PY" "$KIT/kit/merge_settings.py" "$KIT/kit/settings.fragment.json" "$SETTINGS"
say merge "$(rel "$SETTINGS")"

# 5. Git ignore rules.
if git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1; then
  if [ "$MODE" = private ]; then
    EX="$(git -C "$REPO" rev-parse --git-path info/exclude)"
    case "$EX" in /*) ;; *) EX="$REPO/$EX" ;; esac
    mkdir -p "$(dirname "$EX")"; touch "$EX"
    for p in .ai/ .claude/god/ .claude/agents/code-reviewer.md CLAUDE.local.md .claude/settings.local.json \
             .claude/skills/refresh-skeleton/ .claude/skills/onboard-repo/ .claude/skills/trace-flow/ \
             .claude/skills/start-task/ .claude/skills/sync-brain/ .claude/skills/write-lld/ \
             .claude/skills/ops-docs/ .claude/skills/second-opinion/; do
      grep -qxF "$p" "$EX" || echo "$p" >> "$EX"
    done
    say exclude "$(rel "$EX") (kit files stay local, never committed)"
  else
    GI="$REPO/.gitignore"; touch "$GI"
    for p in .ai/review/ .claude/settings.local.json CLAUDE.local.md; do
      grep -qxF "$p" "$GI" || echo "$p" >> "$GI"
    done
    say update ".gitignore (.ai/review/, local settings)"
  fi
else
  echo "  note    not a git repo: skeleton freshness and stop-hook checks are disabled until you git init"
fi

cat <<EOF

Done. Next, in $REPO:
  1. Start Claude Code (check /model shows Opus 5.5) and run:  /onboard-repo
  2. Trace the main business flows:                           /trace-flow <flow>
  3. Work on tasks with the full loop:                        /start-task <description>
  4. LLD / deploy + test docs when needed:                    /write-lld <module>   /ops-docs
  5. High-risk change? Cross-model review with Gemini:        /second-opinion current diff
EOF
[ "$MODE" = shared ] && echo "  Commit AGENTS.md, CLAUDE.md, GEMINI.md, .ai/ and .claude/ so web/phone sessions get the same setup."
[ "$MODE" = private ] && echo "  Private mode: start Antigravity (agy) with \"Read .ai/rules.md first\" since AGENTS.md/GEMINI.md were not added."
exit 0
