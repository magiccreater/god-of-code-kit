#!/usr/bin/env bash
# God of Code kit installer / upgrader.
#   ./install.sh <repo-path>             shared mode: brain + agent config are committed with the repo
#                                        (works in Claude Code on the web / phone, and for teammates)
#   ./install.sh <repo-path> --private   private mode: nothing is committed; all kit files are excluded
#                                        locally via .git/info/exclude (for client/employer repos)
# Safe to re-run: kit-owned files and marked kit blocks are upgraded (kit files you edited are kept, with the
# new version beside them as <file>.kit-new); project knowledge in .ai/ is never overwritten.
set -euo pipefail

KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$KIT/template"
usage() { sed -n '2,8p' "$0"; exit 1; }
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
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >/dev/null 2>&1; then
    PY="$cand"; break
  fi
done
[ -n "$PY" ] || { echo "Python 3.8+ is required (python3 or python)"; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

say() { printf '  %-8s %s\n' "$1" "$2"; }
rel() { printf '%s' "${1#"$REPO"/}"; }
blocks() { "$PY" "$KIT/kit/blocks.py" "$@"; }

echo "Installing God of Code kit into $REPO ($MODE mode)"

# 1. Project brain: copy templates only where nothing exists yet; upgrade the kit block of rules.md.
echo "Project brain (.ai/):"
while IFS= read -r -d '' src; do
  dst="$REPO/${src#"$T"/}"
  if [ -e "$dst" ]; then
    if [ "$(rel "$dst")" = ".ai/rules.md" ]; then
      if grep -qF "god-of-code:core:begin" "$dst"; then
        say "$(blocks upsert "$dst" "$src" core)" ".ai/rules.md (kit sections 1-9; your section 0 kept)"
      else
        cp "$src" "$dst.kit-new"
        say note ".ai/rules.md predates kit markers: new version saved as .ai/rules.md.kit-new — merge your section 0 into it, then replace"
      fi
    else
      say keep "$(rel "$dst")"
    fi
  else
    mkdir -p "$(dirname "$dst")"; cp "$src" "$dst"; say add "$(rel "$dst")"
  fi
done < <(find "$T/.ai" -type f -print0)

# 2. Kit-owned files: installed and upgraded, except ones you edited (kept; new version saved as <file>.kit-new).
echo "Skills, agents, hooks (.claude/):"
"$PY" "$KIT/kit/kit_files.py" install "$T" "$REPO"
chmod +x "$REPO/.claude/god/"*.sh "$REPO/.claude/god/hooks/"*.sh "$REPO/.claude/god/hooks/"*.py \
         "$REPO/.claude/skills/refresh-skeleton/scripts/skeleton.py" 2>/dev/null || true

# 3. Instruction files (kit content lives between <!-- god-of-code:begin/end --> markers).
is_v1_copy() {  # kit v1 copied these files without markers
  local f="$1"
  ! grep -qF "god-of-code:begin" "$f" && {
    { head -n 1 "$f" | grep -qx '@AGENTS.md' && grep -qF '## Claude Code specifics' "$f"; } ||
    { head -n 1 "$f" | grep -qx '# Agent instructions' && grep -qF '@.ai/rules.md' "$f"; } ||
    { head -n 1 "$f" | grep -qx '# Instructions for Gemini / Antigravity agents' && grep -qF 'independent reviewer' "$f"; }
  }
}
install_doc() {  # target template [block-source-for-existing-files]
  local dst="$1" tpl="$2" block_src="${3:-$2}"
  if [ ! -f "$dst" ] || is_v1_copy "$dst"; then
    local how=add; [ -f "$dst" ] && how=update
    cp "$tpl" "$dst"; say "$how" "$(rel "$dst")"
  elif grep -qF "god-of-code:begin" "$dst" && head -n 3 "$dst" | grep -qx '@AGENTS.md'; then
    say "$(blocks upsert "$dst" "$tpl")" "$(rel "$dst")"         # our own CLAUDE.md: keep importing AGENTS.md
  else
    say "$(blocks upsert "$dst" "$block_src")" "$(rel "$dst") (kit block)"
  fi
}
# For a CLAUDE.md the project already had, import the rule book directly instead of AGENTS.md.
sed 's#^@AGENTS\.md$#@.ai/rules.md#' "$T/CLAUDE.md" > "$TMP/claude_block.md"
echo "Instruction files:"
if [ "$MODE" = shared ]; then
  install_doc "$REPO/AGENTS.md" "$T/AGENTS.md"
  install_doc "$REPO/CLAUDE.md" "$T/CLAUDE.md" "$TMP/claude_block.md"
  install_doc "$REPO/GEMINI.md" "$T/GEMINI.md"
  SETTINGS="$REPO/.claude/settings.json"
else
  say "$(blocks upsert "$REPO/CLAUDE.local.md" "$TMP/claude_block.md")" "CLAUDE.local.md"
  SETTINGS="$REPO/.claude/settings.local.json"
fi

# 4. Settings: merge hooks + permissions + model without clobbering.
"$PY" "$KIT/kit/merge_settings.py" "$KIT/kit/settings.fragment.json" "$SETTINGS"
say merge "$(rel "$SETTINGS")"
if "$PY" -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get('model') not in (None, 'opus') else 1)" "$SETTINGS"; then
  say note "$(rel "$SETTINGS") keeps your existing \"model\" setting — check /model if you want Opus"
fi

# 4b. Decision gate: in private mode, mark the repo private so remote models (e.g. Jev) are refused.
if [ "$MODE" = private ] && [ -f "$REPO/.ai/decision-gate.json" ]; then
  "$PY" - "$REPO/.ai/decision-gate.json" <<'PYEOF'
import json, sys
p = sys.argv[1]
with open(p, encoding="utf-8") as fh:
    cfg = json.load(fh)
if cfg.get("private") is not True:
    cfg["private"] = True
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
PYEOF
  say note ".ai/decision-gate.json marked private: remote decision models are refused in this repo"
fi

# 5. Git ignore rules.
if git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1; then
  if [ "$MODE" = private ]; then
    EX="$(git -C "$REPO" rev-parse --git-path info/exclude)"
    case "$EX" in /*) ;; *) EX="$REPO/$EX" ;; esac
    mkdir -p "$(dirname "$EX")"; touch "$EX"
    for p in .ai/ .claude/god/ .claude/agents/code-reviewer.md .claude/agents/qa-skeptic.md CLAUDE.local.md \
             .claude/settings.local.json .claude/skills/refresh-skeleton/ .claude/skills/onboard-repo/ \
             .claude/skills/trace-flow/ .claude/skills/start-task/ .claude/skills/sync-brain/ \
             .claude/skills/write-lld/ .claude/skills/ops-docs/ .claude/skills/second-opinion/ \
             .claude/skills/ready-gate/ .claude/skills/task-ready/ .claude/skills/converge/; do
      grep -qxF "$p" "$EX" || echo "$p" >> "$EX"
    done
    say exclude "$(rel "$EX") (kit files stay local, never committed)"
  else
    GI="$REPO/.gitignore"; touch "$GI"
    for p in .ai/review/ .claude/settings.local.json CLAUDE.local.md __pycache__/; do
      grep -qxF "$p" "$GI" || echo "$p" >> "$GI"
    done
    say update ".gitignore (.ai/review/, local settings)"
  fi
else
  echo "  note     not a git repo: skeleton freshness, stop-hook and test-guard checks stay off until you git init"
fi

if ! "$PY" -c "import tree_sitter_language_pack" >/dev/null 2>&1; then
  say tip "optional: '$PY -m pip install tree-sitter-language-pack' for more accurate skeleton maps"
fi

cat <<EOF

Done. Next, in $REPO:
  WSL and Oracle: god doctor, then god task "your assignment"
  With only this installed repo: bash .claude/god/run.sh task "your assignment"
  1. Start Claude Code (check /model shows Opus 5.5) and run:  /onboard-repo
  2. Trace the main business flows:                           /trace-flow <flow>
  3. Check a task has what it needs (why, AC, repro steps):  /task-ready <description>
     Work on it with the full loop:                          /start-task <T-id>
  4. LLD / deploy + test docs when needed:                    /write-lld <module>   /ops-docs
  5. High-risk change? Cross-model review with Gemini:        /second-opinion current diff
EOF
if [ "$MODE" = shared ]; then
  echo "  Commit AGENTS.md, CLAUDE.md, GEMINI.md, .ai/ and .claude/ so web/phone sessions get the same setup."
else
  echo "  Private mode: start Antigravity (agy) with \"Read .ai/rules.md first\" since AGENTS.md/GEMINI.md were not added."
fi
exit 0
