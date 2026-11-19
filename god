#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
kit=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
case "${1:-help}" in
  init) shift; repo="${1:-.}"; if [[ $# -gt 0 ]]; then shift; fi
        python3 "$kit/template/.claude/god/worker/linux_workspace.py" "$repo"
        bash "$kit/install.sh" "$repo" "$@";;
  self-test) PYTHONPATH="$kit/tests${PYTHONPATH:+:$PYTHONPATH}" GOD_DOCKER_TEST=1 \
             python3 -m unittest -v test_wsl_worker test_aws_gateway;;
  oracle) shift; file="${GOD_ORACLE_PROFILE:-$kit/../limpid-ai-dev-stack/dev-stack-template/oracle/profile}/oracle.sh"
          [[ -f "$file" ]] || { echo "Install both repos side by side or set GOD_ORACLE_PROFILE to the profile directory."; exit 1; }
          bash "$file" "$@";;
  task|review|apply|doctor|status)
        if [[ "$1" =~ ^(task|review)$ && "${2:-}" != --help && "${2:-}" != -h ]]; then
          root=$(git rev-parse --show-toplevel) || { echo "Open a Git repository first."; exit 1; }
          python3 "$kit/template/.claude/god/worker/linux_workspace.py" "$root"
          if [[ ! -f "$root/.ai/rules.md" ]]; then bash "$kit/install.sh" "$root" --private; fi
        fi
        exec python3 "$kit/template/.claude/god/worker/run.py" "$@";;
  *) echo 'god init [repo] [--private] | doctor | self-test | oracle | task "brief" [--single|--parallel] [--public-openrouter] | review "scope" [--public-openrouter] | apply RUN_ID';;
esac
