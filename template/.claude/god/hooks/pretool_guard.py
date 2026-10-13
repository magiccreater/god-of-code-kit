#!/usr/bin/env python3
"""PreToolUse guard for the God of Code kit.

1. Protect existing tests: editing, overwriting, moving or deleting a test file that already
   exists in HEAD needs the human's approval ("ask"). New test files are never blocked.
2. Commit nudge: `git commit` whose changes touch source code but no tests asks the human first.

Reads the hook JSON on stdin. Prints a PreToolUse "ask" decision, or nothing (normal permission
flow). Any internal error fails open (prints nothing): this is a guard rail, not a gate.
"""
import json
import os
import re
import shlex
import subprocess
import sys

SOURCE_EXT = {
    ".php", ".py", ".rb", ".go", ".rs", ".java", ".kt", ".kts", ".scala", ".cs", ".swift",
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
}
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "testing", "e2e", "integration_tests"}
TEST_NAME = re.compile(
    r"(^test_.+\.py$|.+_test\.(py|go|rs|cc|cpp|c|rb)$|.+\.(test|spec)\.[cm]?[jt]sx?$|"
    r".+Tests?\.(php|java|kt|cs|swift)$|.+_spec\.rb$|^test_.+\.(c|cc|cpp)$)")
NON_CODE_DIRS = {".ai", ".claude", "docs", "doc"}


def git(root, *args):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=20)
    return r.stdout if r.returncode == 0 else ""


def is_test(rel):
    parts = rel.replace("\\", "/").split("/")
    return any(p.lower() in TEST_DIRS for p in parts[:-1]) or bool(TEST_NAME.match(parts[-1]))


def is_source(rel):
    parts = rel.replace("\\", "/").split("/")
    if parts[0] in NON_CODE_DIRS:
        return False
    return os.path.splitext(parts[-1])[1].lower() in SOURCE_EXT


def to_rel(root, path, cwd):
    if not path:
        return None
    p = path if os.path.isabs(path) else os.path.join(cwd, path)
    try:
        rel = os.path.relpath(os.path.realpath(p), os.path.realpath(root))
    except ValueError:  # different drive on Windows
        return None
    rel = rel.replace("\\", "/")
    return None if rel.startswith("../") or rel == ".." else rel


def in_head(root, rel):
    r = subprocess.run(["git", "-C", root, "cat-file", "-e", f"HEAD:{rel}"],
                       capture_output=True, timeout=20)
    return r.returncode == 0


def ask(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": reason,
    }}))
    sys.exit(0)


def protected(root, rel):
    return rel is not None and is_test(rel) and in_head(root, rel)


TEST_GUARD_MSG = ("{f} is an existing test (it is in HEAD). Changing existing tests can hide "
                  "regressions. Approve only if the test itself is wrong or the intended behaviour "
                  "changed; otherwise add a new test instead.")


def check_file_tool(root, cwd, tool_input):
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path")
    rel = to_rel(root, path, cwd)
    if protected(root, rel):
        ask(TEST_GUARD_MSG.format(f=rel))


WRITE_ALL_ARGS = {"rm", "unlink", "mv", "truncate", "shred"}
WRITE_LAST_ARG = {"cp", "install", "ln", "rsync"}


def split_commands(command):
    # split on shell separators while keeping quoted text intact
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = command.split()
    cmds, cur = [], []
    for tok in tokens:
        if tok and set(tok) <= set(";&|"):
            if cur:
                cmds.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        cmds.append(cur)
    return cmds


def bash_test_targets(command):
    """Return paths a shell command would write/delete (best effort)."""
    targets = []
    # redirections: > file, >> file, &> file
    for m in re.finditer(r"(?:^|[^<>&\d])\d?&?>>?\s*([^\s;&|<>]+)", command):
        targets.append(m.group(1).strip("'\""))
    for argv in split_commands(command):
        while argv and re.match(r"^\w+=", argv[0]):  # env assignments
            argv = argv[1:]
        if not argv:
            continue
        prog = os.path.basename(argv[0])
        args = [a for a in argv[1:] if not a.startswith("-")]
        if prog in ("sed", "perl", "ruby") and any(a == "-i" or a.startswith("-i") or a == "--in-place"
                                                   for a in argv[1:]):
            targets += args[1:] if prog == "sed" else args
        elif prog in WRITE_ALL_ARGS:
            targets += args
        elif prog in WRITE_LAST_ARG and args:
            targets.append(args[-1])
        elif prog == "tee":
            targets += args
        elif prog == "git" and len(argv) > 1 and argv[1] in ("checkout", "restore", "rm", "mv"):
            after = argv[argv.index("--") + 1:] if "--" in argv else [a for a in argv[2:] if not a.startswith("-")]
            targets += after
    return targets


def check_bash(root, cwd, command):
    if not command:
        return
    for t in bash_test_targets(command):
        rel = to_rel(root, t, cwd)
        if protected(root, rel):
            ask(TEST_GUARD_MSG.format(f=rel) + " (shell command writes, moves or deletes it)")
    check_commit(root, command)


def check_commit(root, command):
    for argv in split_commands(command):
        if len(argv) < 2 or os.path.basename(argv[0]) != "git":
            continue
        # allow `git -C dir commit` and `git -c k=v commit`
        i = 1
        while i < len(argv) and argv[i] in ("-C", "-c"):
            i += 2
        if i >= len(argv) or argv[i] != "commit":
            continue
        opts = argv[i + 1:]
        if "--amend" in opts and not any(o.startswith("-m") or o == "--message" for o in opts):
            continue
        commit_all = any(o in ("-a", "--all") or (re.match(r"^-[a-zA-Z]+$", o) and "a" in o[1:])
                         for o in opts)
        files = set(git(root, "diff", "--cached", "--name-only").splitlines())
        if commit_all:
            files |= set(git(root, "diff", "--name-only").splitlines())
        files = {f for f in files if f}
        code = sorted(f for f in files if is_source(f) and not is_test(f))
        tests = [f for f in files if is_test(f)]
        if code and not tests:
            shown = ", ".join(code[:5]) + (f" (+{len(code) - 5} more)" if len(code) > 5 else "")
            ask(f"This commit changes source code ({shown}) but no test files. "
                f"Approve to commit anyway, or decline and add a regression test first.")


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    cwd = data.get("cwd") or os.getcwd()
    root = os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    top = git(cwd, "rev-parse", "--show-toplevel").strip()
    if "/.ai/review/worktrees/" in top.replace("\\", "/") + "/":
        return  # scratch QA worktree: tests there are disposable
    if top:
        root = top
    elif not git(root, "rev-parse", "--show-toplevel").strip():
        return  # not a git repo: nothing to compare against
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        check_file_tool(root, cwd, tool_input)
    elif tool in ("Bash", "PowerShell"):
        check_bash(root, cwd, tool_input.get("command", ""))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        pass  # fail open
