#!/usr/bin/env bash
# Scratch git worktrees for the qa-skeptic agent. Never touches the main working tree's files.
#
#   qa_worktree.sh changed                 list files changed vs HEAD in the main tree (tracked + untracked)
#   qa_worktree.sh create                  new worktree at HEAD (clean base); prints its path
#   qa_worktree.sh add-file <wt> <file>... copy files from the main tree into the worktree
#   qa_worktree.sh apply <wt>              make the worktree = HEAD + the main tree's current changes
#   qa_worktree.sh remove <wt>             unlink dependency links, remove the worktree
#   qa_worktree.sh cleanup                 remove every QA worktree (use after crashes)
#
# Worktrees live in .ai/review/worktrees/ (gitignored). Dependency folders that git does not track
# (vendor, node_modules, virtualenvs) are linked from the main tree, and env files are copied, so tests
# can run without reinstalling. Links are recorded in <wt>/.qa-links and unlinked before removal.
set -euo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
ROOT="$(git -C "$ROOT" rev-parse --show-toplevel)"
BASE="$ROOT/.ai/review/worktrees"
DEP_DIRS=(vendor node_modules .venv venv)
ENV_FILES=(.env .env.testing .env.test .env.test.local phpunit.xml)
IS_WINDOWS=0
case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=1 ;; esac

die() { echo "qa_worktree: $*" >&2; exit 1; }

check_wt() {
  [ -n "${1:-}" ] || die "worktree path required"
  case "$(cd "$1" 2>/dev/null && pwd)/" in "$BASE"/qa-*/*) ;; *) die "not a QA worktree: $1" ;; esac
}

link_dir() {  # target link
  local target="$1" link="$2"
  mkdir -p "$(dirname "$link")"
  if [ "$IS_WINDOWS" = 1 ] && command -v cygpath >/dev/null 2>&1; then
    cmd //c mklink /J "$(cygpath -w "$link")" "$(cygpath -w "$target")" >/dev/null
  else
    ln -s "$target" "$link"
  fi
}

unlink_dir() {
  local link="$1"
  [ -e "$link" ] || [ -L "$link" ] || return 0
  if [ "$IS_WINDOWS" = 1 ] && command -v cygpath >/dev/null 2>&1; then
    cmd //c rmdir "$(cygpath -w "$link")" >/dev/null 2>&1 || rm -f "$link"
  else
    rm -f "$link"   # removes the link only, never the target
  fi
}

changed() {
  {
    git -C "$ROOT" diff --name-only HEAD
    git -C "$ROOT" ls-files --others --exclude-standard
  } | grep -v -E '^\.(ai|claude)/' | sort -u
}

create() {
  mkdir -p "$BASE"
  local wt="$BASE/qa-$(date +%Y%m%d-%H%M%S)-$$"
  git -C "$ROOT" worktree add --detach --quiet "$wt" HEAD
  : > "$wt/.qa-links"
  # dependency folders (not tracked by git), at the root and up to 3 levels deep for monorepos
  while IFS= read -r dep; do
    local rel="${dep#"$ROOT"/}"
    case "$rel" in .ai/*|.git/*|*/node_modules/*|*/vendor/*) continue ;; esac
    if [ ! -e "$wt/$rel" ] && ! git -C "$ROOT" ls-files --error-unmatch "$rel" >/dev/null 2>&1; then
      link_dir "$dep" "$wt/$rel" && echo "$rel" >> "$wt/.qa-links"
    fi
  done < <(find "$ROOT" -maxdepth 3 \( -path "$ROOT/.git" -o -path "$ROOT/.ai" \) -prune -o \
             -type d \( -name vendor -o -name node_modules -o -name .venv -o -name venv \) -print -prune 2>/dev/null)
  for f in "${ENV_FILES[@]}"; do
    if [ -f "$ROOT/$f" ] && [ ! -e "$wt/$f" ]; then cp "$ROOT/$f" "$wt/$f"; fi
  done
  echo "$wt"
}

add_file() {
  local wt="$1"; shift
  check_wt "$wt"
  for f in "$@"; do
    f="${f#"$ROOT"/}"
    [ -f "$ROOT/$f" ] || die "no such file in main tree: $f"
    mkdir -p "$(dirname "$wt/$f")"
    cp "$ROOT/$f" "$wt/$f"
  done
}

apply_changes() {
  local wt="$1"
  check_wt "$wt"
  git -C "$wt" checkout --quiet -- .           # tracked files back to HEAD (untracked/links untouched)
  local patch
  patch="$(git -C "$ROOT" diff HEAD --binary -- . ':(exclude).ai' ':(exclude).claude')"
  if [ -n "$patch" ]; then
    printf '%s\n' "$patch" | git -C "$wt" apply --whitespace=nowarn
  fi
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    mkdir -p "$(dirname "$wt/$f")"
    cp "$ROOT/$f" "$wt/$f"
  done < <(git -C "$ROOT" ls-files --others --exclude-standard | grep -v -E '^\.(ai|claude)/' || true)
  echo "applied main-tree changes to $wt"
}

remove() {
  local wt="$1"
  check_wt "$wt"
  if [ -f "$wt/.qa-links" ]; then
    while IFS= read -r rel; do [ -n "$rel" ] && unlink_dir "$wt/$rel"; done < "$wt/.qa-links"
  fi
  git -C "$ROOT" worktree remove --force "$wt" 2>/dev/null || rm -rf "$wt"
  git -C "$ROOT" worktree prune
  echo "removed $wt"
}

cleanup() {
  [ -d "$BASE" ] || { git -C "$ROOT" worktree prune; echo "nothing to clean"; return 0; }
  for wt in "$BASE"/qa-*; do [ -d "$wt" ] && remove "$wt"; done
  git -C "$ROOT" worktree prune
}

cmd="${1:-}"; shift || true
case "$cmd" in
  changed)  changed ;;
  create)   create ;;
  add-file) add_file "$@" ;;
  apply)    apply_changes "${1:-}" ;;
  remove)   remove "${1:-}" ;;
  cleanup)  cleanup ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
