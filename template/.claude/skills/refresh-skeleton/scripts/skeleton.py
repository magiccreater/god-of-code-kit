#!/usr/bin/env python3
"""Generate .ai/context/skeleton.md - a compact map of a repository (skeletonization).

Lists entry points (routes, schedules, jobs, commands, pages), a directory overview and,
per file, classes / functions / methods with line numbers. Bodies are never included.
Pure standard library; regex-based, so it is fast and approximate by design.

Usage: python3 skeleton.py [REPO_ROOT] [--out PATH] [--max-chars N] [--include DIR ...]
"""
import argparse
import collections
import datetime
import os
import re
import subprocess
import sys

EXT_LANG = {
    ".php": "php",
    ".ts": "ts", ".tsx": "ts", ".js": "ts", ".jsx": "ts", ".mjs": "ts", ".cjs": "ts", ".vue": "ts",
    ".py": "py", ".go": "go", ".java": "java", ".kt": "java", ".cs": "cs", ".rb": "rb",
}
SKIP_PARTS = {
    "node_modules", "vendor", ".git", "dist", "build", ".next", ".nuxt", "out", "coverage",
    ".venv", "venv", "__pycache__", ".ai", ".claude", ".idea", ".vscode", "bin", "obj",
    ".turbo", ".cache", "target",
}
SKIP_PREFIXES = ("storage/", "bootstrap/cache/", "public/build/", "public/vendor/")
SKIP_FILE = re.compile(r"(\.min\.(js|css)$|\.d\.ts$|\.map$|\.bundle\.js$|-lock\.|\.lock$|\.generated\.)")
MAX_FILE_BYTES = 800_000
MAX_SYMBOLS_PER_FILE = 40
JS_KEYWORDS = {"if", "for", "while", "switch", "catch", "function", "return", "constructor_", "else",
               "do", "try", "with", "typeof", "new", "await", "super", "import"}


def clip(s, n=90):
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s if len(s) <= n else s[: n - 1] + "…"


def run_git(root, *args):
    try:
        return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True,
                              timeout=60).stdout
    except Exception:
        return ""


def list_files(root, includes):
    out = run_git(root, "ls-files", "-co", "--exclude-standard")
    files = [l for l in out.splitlines() if l.strip()]
    if not files:
        for d, dirs, fs in os.walk(root):
            dirs[:] = [x for x in dirs if x not in SKIP_PARTS]
            for f in fs:
                files.append(os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/"))
    res = []
    for f in files:
        parts = f.split("/")
        if any(p in SKIP_PARTS for p in parts[:-1]) or f.startswith(SKIP_PREFIXES):
            continue
        if includes and not any(f == i or f.startswith(i.rstrip("/") + "/") for i in includes):
            continue
        if SKIP_FILE.search(f):
            continue
        if os.path.splitext(f)[1].lower() not in EXT_LANG:
            continue
        p = os.path.join(root, f)
        try:
            if os.path.getsize(p) > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        res.append(f)
    return sorted(res)


def php_mods(mods):
    keep = [x for x in (mods or "").split() if x in ("protected", "private", "static", "abstract")]
    return (" ".join(keep) + " ") if keep else ""


# ---------------------------------------------------------------- symbol rules
# Each rule: (regex, formatter(match) -> text, member?)  member=True means indented under a type.

PHP_RULES = [
    (re.compile(r"^\s*(?:final\s+|abstract\s+|readonly\s+)*(class|interface|trait|enum)\s+(\w+)([^{]*)"),
     lambda m: f"{m.group(1)} {m.group(2)}{(' ' + clip(m.group(3), 70)) if m.group(3).strip() else ''}", False),
    (re.compile(r"^(\s*)((?:(?:public|protected|private|static|final|abstract)\s+)*)function\s+&?(\w+)\s*\(([^)]*)\)?\s*(?::\s*([?\w\\|]+))?"),
     lambda m: f"{php_mods(m.group(2))}{m.group(3)}({clip(m.group(4), 60)}){': ' + m.group(5) if m.group(5) else ''}",
     None),
]
TS_RULES = [
    (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)([^{]*)"),
     lambda m: f"class {m.group(1)}{(' ' + clip(m.group(2), 60)) if m.group(2).strip() else ''}", False),
    (re.compile(r"^\s*(?:export\s+)?(?:declare\s+)?(interface|type|enum)\s+(\w+)"),
     lambda m: f"{m.group(1)} {m.group(2)}", False),
    (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)?"),
     lambda m: f"function {m.group(1)}({clip(m.group(2), 60)})", False),
    (re.compile(r"^\s*(?:export\s+)?const\s+(\w+)\s*(?::[^=]+)?=\s*(?:async\s+)?(?:\(([^)]*)\)|(\w+))\s*(?::[^=]+)?=>"),
     lambda m: f"const {m.group(1)} = ({clip(m.group(2) or m.group(3) or '', 60)}) =>", False),
    (re.compile(r"^\s+(?:(?:public|private|protected|static|async|readonly|override|get|set)\s+)*(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)\s*(?::\s*([^{=]+?))?\s*\{\s*$"),
     lambda m: None if m.group(1) in JS_KEYWORDS else f"{m.group(1)}({clip(m.group(2), 60)}){': ' + clip(m.group(3), 40) if m.group(3) else ''}", True),
]
PY_RULES = [
    (re.compile(r"^(\s*)class\s+(\w+)(\([^)]*\))?\s*:"),
     lambda m: f"class {m.group(2)}{m.group(3) or ''}", None),
    (re.compile(r"^(\s*)(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)?(?:\s*->\s*([^:]+))?"),
     lambda m: f"def {m.group(2)}({clip(m.group(3), 60)}){' -> ' + clip(m.group(4), 30) if m.group(4) else ''}", None),
]
GO_RULES = [
    (re.compile(r"^type\s+(\w+)\s+(struct|interface)"), lambda m: f"type {m.group(1)} {m.group(2)}", False),
    (re.compile(r"^func\s+(\([^)]*\)\s*)?(\w+)\s*\(([^)]*)\)?"),
     lambda m: f"func {(m.group(1) or '').strip() + ' ' if m.group(1) else ''}{m.group(2)}({clip(m.group(3), 60)})", False),
]
JAVA_RULES = [
    (re.compile(r"^\s*(?:(?:public|private|protected|internal|abstract|final|static|sealed|partial|data|open)\s+)*(class|interface|enum|record|object)\s+(\w+)([^{]*)"),
     lambda m: f"{m.group(1)} {m.group(2)}{(' ' + clip(m.group(3), 60)) if m.group(3).strip() else ''}", False),
    (re.compile(r"^\s+(?:(?:public|protected|internal|private|static|final|abstract|override|async|virtual|suspend|open)\s+)+(?:fun\s+)?[\w<>\[\],.?\s]*?\b(\w+)\s*\(([^)]*)\)?"),
     lambda m: None if m.group(1) in JS_KEYWORDS else f"{m.group(1)}({clip(m.group(2), 60)})", True),
]
RB_RULES = [
    (re.compile(r"^(\s*)(class|module)\s+([\w:]+)(\s*<\s*[\w:]+)?"),
     lambda m: f"{m.group(2)} {m.group(3)}{m.group(4) or ''}", None),
    (re.compile(r"^(\s*)def\s+(self\.)?(\w+[?!=]?)(\([^)]*\))?"),
     lambda m: f"def {m.group(2) or ''}{m.group(3)}{m.group(4) or ''}", None),
]
RULES = {"php": PHP_RULES, "ts": TS_RULES, "py": PY_RULES, "go": GO_RULES, "java": JAVA_RULES,
         "cs": JAVA_RULES, "rb": RB_RULES}

# ---------------------------------------------------------------- entry points
LARAVEL_ROUTE = re.compile(
    r"Route::(get|post|put|patch|delete|any|match|resource|apiResource|view|redirect)\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*(.+?))?\)\s*(?:->name\(['\"]([^'\"]+)['\"]\))?")
LARAVEL_SCHEDULE = re.compile(r"(?:\$schedule->|Schedule::)(command|job|call|exec)\(([^;]*)")
EXPRESS_ROUTE = re.compile(r"\b(app|router|server|fastify)\.(get|post|put|patch|delete|all|use)\(\s*['\"`]([^'\"`]+)['\"`]")
NEST_ROUTE = re.compile(r"@(Get|Post|Put|Patch|Delete)\(\s*['\"]?([^'\")]*)")
FLASK_ROUTE = re.compile(r"@\w+\.(route|get|post|put|patch|delete)\(\s*['\"]([^'\"]+)")
ENTRY_DIR_TAGS = [
    ("/Console/Commands/", "COMMAND"), ("/Jobs/", "JOB"), ("/Listeners/", "LISTENER"),
    ("/Events/", "EVENT"), ("/Mail/", "MAIL"), ("/Notifications/", "NOTIFICATION"),
    ("/Webhooks/", "WEBHOOK"), ("/Middleware/", "MIDDLEWARE"), ("/Policies/", "POLICY"),
]
NEXT_PAGE = re.compile(r"(^|/)app/(.*/)?(page|route|layout)\.(tsx|ts|jsx|js)$")
NEXT_PAGES_API = re.compile(r"(^|/)pages/(api/.*)\.(tsx|ts|jsx|js)$")


def clean_handler(h):
    h = (h or "").replace("::class", "")
    m = re.match(r"\s*\[\s*([\w\\]+)\s*,\s*['\"](\w+)['\"]\s*\]", h)
    if m:
        return f"{m.group(1).split(chr(92))[-1]}@{m.group(2)}"
    return clip(h, 70).strip(" ,")


def scan_file(rel, text, lang, entries):
    lines = text.splitlines()
    symbols = []
    rules = RULES.get(lang, [])
    for i, line in enumerate(lines, 1):
        if lang == "php":
            m = LARAVEL_ROUTE.search(line)
            if m:
                verb, uri, handler, name = m.groups()
                entries.append(f"ROUTE {verb.upper()} {uri}"
                               f"{' → ' + clean_handler(handler) if handler else ''}"
                               f"{' [' + name + ']' if name else ''}  ({rel}:{i})")
            m = LARAVEL_SCHEDULE.search(line)
            if m:
                entries.append(f"SCHEDULE {m.group(1)} {clip(m.group(2), 80)}  ({rel}:{i})")
        elif lang == "ts":
            m = EXPRESS_ROUTE.search(line)
            if m and m.group(2) != "use":
                entries.append(f"ROUTE {m.group(2).upper()} {m.group(3)}  ({rel}:{i})")
            m = NEST_ROUTE.search(line)
            if m:
                entries.append(f"ROUTE {m.group(1).upper()} {m.group(2) or '/'}  ({rel}:{i})")
        elif lang == "py":
            m = FLASK_ROUTE.search(line)
            if m:
                entries.append(f"ROUTE {m.group(1).upper()} {m.group(2)}  ({rel}:{i})")
        if len(symbols) >= MAX_SYMBOLS_PER_FILE:
            continue
        for rx, fmt, member in rules:
            m = rx.match(line)
            if not m:
                continue
            text_out = fmt(m)
            if not text_out:
                break
            if member is None:  # decide by indentation
                is_member = bool(line[: len(line) - len(line.lstrip())])
            else:
                is_member = member
            symbols.append((1 if is_member else 0, text_out, i))
            break
    return symbols, len(lines)


def build(root, max_chars, includes):
    files = list_files(root, includes)
    head = run_git(root, "rev-parse", "--short", "HEAD").strip() or "none"
    entries, per_file = [], []
    dir_counts = collections.Counter()
    for rel in files:
        lang = EXT_LANG[os.path.splitext(rel)[1].lower()]
        try:
            with open(os.path.join(root, rel), encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        parts = rel.split("/")
        dir_counts["/".join(parts[:2]) if len(parts) > 2 else (parts[0] if len(parts) > 1 else ".")] += 1
        if NEXT_PAGE.search(rel) or NEXT_PAGES_API.search(rel):
            entries.append(f"PAGE/ROUTE {rel}")
        for frag, tag in ENTRY_DIR_TAGS:
            if frag in "/" + rel:
                entries.append(f"{tag} {rel}")
                break
        symbols, nlines = scan_file(rel, text, lang, entries)
        per_file.append((rel, nlines, symbols))

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    header = [
        "# Code skeleton",
        "",
        f"Generated: {now} · Generated at commit: {head} · Files mapped: {len(per_file)}",
        "Generated by the refresh-skeleton skill. Approximate (regex-based). Line numbers point to definitions:",
        "read only the ranges you need. Search this file with grep instead of reading it whole.",
        "",
    ]
    ent = ["## Entry points", ""] + ([f"- {e}" for e in entries[:400]] or ["- (none detected)"])
    if len(entries) > 400:
        ent.append(f"- … {len(entries) - 400} more")
    ent.append("")
    ov = ["## Directory overview (code files)", ""] + [f"- {d}: {n}" for d, n in sorted(dir_counts.items())] + [""]

    def render(include_members):
        out = ["## Symbols", ""]
        for rel, nlines, syms in per_file:
            shown = [s for s in syms if include_members or s[0] == 0]
            if not shown:
                continue
            out.append(f"### {rel} ({nlines} lines)")
            for depth, txt, ln in shown:
                out.append(f"{'  ' * depth}- {txt}  :{ln}")
            if len(syms) >= MAX_SYMBOLS_PER_FILE:
                out.append("  - … (symbol cap reached)")
            out.append("")
        return out

    base = header + ent + ov
    body = render(True)
    mode = "full"
    if len("\n".join(base + body)) > max_chars:
        body = render(False)
        mode = "top-level only (members dropped to fit --max-chars)"
    text = "\n".join(base + body)
    if len(text) > max_chars:
        text = text[:max_chars].rsplit("\n### ", 1)[0] + \
            "\n\n… truncated to fit --max-chars. Use --include <dir> for a focused map.\n"
        mode += ", truncated"
    return text, len(per_file), len(entries), mode


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=os.environ.get("CLAUDE_PROJECT_DIR", "."))
    ap.add_argument("--out", default=None, help="output path (default: <root>/.ai/context/skeleton.md)")
    ap.add_argument("--max-chars", type=int, default=60000)
    ap.add_argument("--include", action="append", default=[], help="only map this directory (repeatable)")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    out = a.out or os.path.join(root, ".ai", "context", "skeleton.md")
    text, nfiles, nentries, mode = build(root, a.max_chars, [i.strip("./") for i in a.include])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"Wrote {os.path.relpath(out, root)}: {nfiles} files, {nentries} entry points, "
          f"{len(text):,} chars, mode: {mode}")


if __name__ == "__main__":
    sys.exit(main())
