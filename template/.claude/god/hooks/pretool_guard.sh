#!/usr/bin/env bash
# PreToolUse hook wrapper: finds a working Python and runs pretool_guard.py with the hook JSON on stdin.
# Without a working Python it does nothing (normal permission flow applies).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for cand in python3 python "py -3"; do
  # shellcheck disable=SC2086
  if $cand -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" </dev/null >/dev/null 2>&1; then
    # shellcheck disable=SC2086
    exec $cand "$DIR/pretool_guard.py"
  fi
done
cat >/dev/null
exit 0
