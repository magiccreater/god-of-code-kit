#!/usr/bin/env bash
set -euo pipefail
grep -qi microsoft /proc/sys/kernel/osrelease || { echo "Run this in WSL Ubuntu."; exit 1; }
kit=$(cd "$(dirname "$0")" && pwd)
python3 "$kit/template/.claude/god/worker/linux_workspace.py" "$kit"
bin="$HOME/.local/bin"
mkdir -p "$bin"
if [[ -e "$bin/god" && "$(readlink -f "$bin/god")" != "$kit/god" ]]; then
  echo "Existing $bin/god kept. Run $kit/god directly."; exit 1
fi
chmod +x "$kit/god"
ln -sfn "$kit/god" "$bin/god"
echo "Installed $bin/god. In a project, run god task 'your assignment'."
case ":$PATH:" in *":$bin:"*) ;; *) echo 'Add ~/.local/bin to PATH or use ~/.local/bin/god.' ;; esac
