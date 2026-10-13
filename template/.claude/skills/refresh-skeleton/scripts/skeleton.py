#!/usr/bin/env python3
"""Generate .ai/context/skeleton.md - a compact map of a repository (skeletonization).

Lists entry points (routes, schedules, jobs, commands, pages, mains), a directory overview and,
per file, classes / functions / methods with line numbers. Bodies are never included.

Engines:
  regex       standard library only; fast and approximate (default when tree-sitter is absent)
  tree-sitter accurate parsing via the optional `tree-sitter-language-pack` package
              (pip install tree-sitter-language-pack); grammars download on first use.
  auto        tree-sitter per language when available, regex otherwise (default)

Usage: python3 skeleton.py [REPO_ROOT] [--out PATH] [--max-chars N] [--include DIR ...]
                           [--engine auto|regex|tree-sitter]
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
    ".rs": "rs",
    ".c": "cpp", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".c++": "cpp", ".ipp": "cpp",
    ".h": "cpph", ".hh": "cpph", ".hpp": "cpph", ".hxx": "cpph", ".h++": "cpph", ".inl": "cpph",
}
# tree-sitter grammar names by extension (only used by the tree-sitter engine)
EXT_TS = {
    ".php": "php", ".ts": "typescript", ".tsx": "tsx", ".js": "javascript", ".jsx": "javascript",
    ".mjs": "javascript", ".cjs": "javascript", ".py": "python", ".go": "go", ".java": "java",
    ".kt": "kotlin", ".cs": "csharp", ".rb": "ruby", ".rs": "rust", ".c": "c",
    ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".c++": "cpp", ".ipp": "cpp",
    ".h": "cpp", ".hh": "cpp", ".hpp": "cpp", ".hxx": "cpp", ".h++": "cpp", ".inl": "cpp",
}
SKIP_PARTS = {
    "node_modules", "vendor", ".git", "dist", "build", ".next", ".nuxt", "out", "coverage",
    ".venv", "venv", "__pycache__", ".ai", ".claude", ".idea", ".vscode", "bin", "obj",
    ".turbo", ".cache", "target", "cmake-build-debug", "cmake-build-release", "_deps", "third_party",
}
SKIP_PREFIXES = ("storage/", "bootstrap/cache/", "public/build/", "public/vendor/")
SKIP_FILE = re.compile(r"(\.min\.(js|css)$|\.d\.ts$|\.map$|\.bundle\.js$|-lock\.|\.lock$|\.generated\.|\.pb\.(h|cc)$)")
MAX_FILE_BYTES = 800_000
MAX_SYMBOLS_PER_FILE = 40
JS_KEYWORDS = {"if", "for", "while", "switch", "catch", "function", "return", "constructor_", "else",
               "do", "try", "with", "typeof", "new", "await", "super", "import"}
CPP_NOT_TYPES = {"return", "else", "if", "while", "for", "switch", "case", "delete", "new", "throw",
                 "goto", "sizeof", "co_return", "co_await", "co_yield", "using", "typedef", "do",
                 "default", "public", "private", "protected", "static_assert", "decltype", "alignof"}
CPP_NOT_NAMES = {"if", "while", "for", "switch", "catch", "return", "sizeof", "defined", "decltype",
                 "static_assert", "alignof", "noexcept", "assert", "__attribute__"}


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


def cpp_fn(m):
    ret, name = m.group(2).split(), m.group(3)
    if ret and ret[0] in CPP_NOT_TYPES or name.split("::")[-1] in CPP_NOT_NAMES:
        return None
    ret_txt = clip(m.group(2), 40)
    mods = (" " + clip(m.group(5), 20)) if m.group(5) and m.group(5).strip() else ""
    return f"{ret_txt + ' ' if ret_txt else ''}{name}({clip(m.group(4), 60)}){mods}"


# ---------------------------------------------------------------- regex symbol rules
# Each rule: (regex, formatter(match) -> text or None, member?)
# member: True = indented under a type, False = top level, None = decide by indentation.

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
_RS_VIS = r"(?:pub(?:\s*\([^)]*\))?\s+)?"
RS_RULES = [
    (re.compile(r"^(\s*)" + _RS_VIS + r"(?:(?:const|async|unsafe|default)\s+)*(?:extern\s+\"[^\"]*\"\s+)?fn\s+(\w+)\s*(<[^(]*?>)?\s*\(([^)]*)\)?(?:\s*->\s*([^{;]+))?"),
     lambda m: f"fn {m.group(2)}{m.group(3) or ''}({clip(m.group(4), 60)}){' -> ' + clip(m.group(5), 40) if m.group(5) else ''}", None),
    (re.compile(r"^(\s*)" + _RS_VIS + r"(struct|enum|trait|union|type|mod)\s+(\w+)"),
     lambda m: f"{m.group(2)} {m.group(3)}", None),
    (re.compile(r"^(\s*)(?:unsafe\s+)?impl\b\s*(<[^{]*?>)?\s*([^{]+?)\s*(?:\{.*|where\b.*)?$"),
     lambda m: f"impl {clip(m.group(3), 70)}", None),
    (re.compile(r"^(\s*)macro_rules!\s*(\w+)"), lambda m: f"macro_rules! {m.group(2)}", None),
]
_CPP_TYPE = re.compile(
    r"^(\s*)(?:typedef\s+)?(?:template\s*<.*>\s*)?(class|struct|union|enum(?:\s+class|\s+struct)?)\s+"
    r"(?:\[\[[^\]]*\]\]\s*)?(?:\w+_(?:API|EXPORT)\s+)?(\w+)\s*(final\s*)?(:[^;{]*)?\s*(?:\{.*)?$")
_CPP_NS = re.compile(r"^(\s*)(?:inline\s+)?namespace\s+([\w:]+)\s*\{?\s*$")
_CPP_TARGS = r"(?:<[^()]*?>)?"
_CPP_NAME = r"(~?\w+" + _CPP_TARGS + r"(?:::~?\w+" + _CPP_TARGS + r")*|operator\s*[^\s(]+)"
_CPP_MODS = r"((?:const|override|final|noexcept(?:\([^)]*\))?|volatile|&&|&|->\s*[\w:<>*&]+|\s)*)"
_CPP_FN = (r"^(\s*)(?:template\s*<.*?>\s*)?"
           r"((?:[\w:]+" + _CPP_TARGS + r"[\s*&]+)+)"
           + _CPP_NAME + r"\s*\(([^;{}]*?)")
CPP_RULES = [
    (_CPP_NS, lambda m: f"namespace {m.group(2)}", None),
    (_CPP_TYPE, lambda m: f"{m.group(2)} {m.group(3)}{(' ' + clip(m.group(5), 60)) if m.group(5) else ''}", None),
    # definitions: body on this line, brace on the next line, ctor initializer, or params continuing (",")
    (re.compile(_CPP_FN + r"(?:\)\s*" + _CPP_MODS + r"\s*(?:\{.*|:\s*\w.*)?|,)\s*$"), cpp_fn, None),
    # out-of-class constructors/destructors: Foo::Foo(int x) : a(x) {   /   Vec<T>::Vec(T x) {
    (re.compile(r"^(\s*)()((?:\w+" + _CPP_TARGS + r"::)+~?\w+)\s*\(([^;]*?)\)\s*()(?::.*|\{.*|)$"), cpp_fn, None),
]
CPPH_RULES = CPP_RULES + [
    # declarations in headers: int add(int a, int b); / virtual void run() = 0;
    (re.compile(_CPP_FN + r"\)\s*" + _CPP_MODS + r"\s*(?:=\s*(?:0|default|delete)\s*)?;\s*(?://.*)?$"), cpp_fn, None),
    # constructor / destructor declarations inside a class: Vec(T x, T y); explicit Vec(int n);
    (re.compile(r"^(\s+)((?:explicit\s+|virtual\s+|constexpr\s+)*)(~?[A-Z]\w*)\s*\(([^;{}]*)\)\s*()(?:noexcept\s*)?(?:=\s*(?:default|delete)\s*)?;\s*$"),
     lambda m: f"{m.group(2)}{m.group(3)}({clip(m.group(4), 60)})", None),
]
RULES = {"php": PHP_RULES, "ts": TS_RULES, "py": PY_RULES, "go": GO_RULES, "java": JAVA_RULES,
         "cs": JAVA_RULES, "rb": RB_RULES, "rs": RS_RULES, "cpp": CPP_RULES, "cpph": CPPH_RULES}

# ---------------------------------------------------------------- entry points
LARAVEL_ROUTE = re.compile(
    r"Route::(get|post|put|patch|delete|any|match|resource|apiResource|view|redirect)\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*(.+?))?\)\s*(?:->name\(['\"]([^'\"]+)['\"]\))?")
LARAVEL_SCHEDULE = re.compile(r"(?:\$schedule->|Schedule::)(command|job|call|exec)\(([^;]*)")
EXPRESS_ROUTE = re.compile(r"\b(app|router|server|fastify)\.(get|post|put|patch|delete|all|use)\(\s*['\"`]([^'\"`]+)['\"`]")
NEST_ROUTE = re.compile(r"@(Get|Post|Put|Patch|Delete)\(\s*['\"]?([^'\")]*)")
FLASK_ROUTE = re.compile(r"@\w+\.(route|get|post|put|patch|delete)\(\s*['\"]([^'\"]+)")
RUST_ATTR_ROUTE = re.compile(r"#\[(get|post|put|patch|delete)\(\s*\"([^\"]+)\"")
RUST_AXUM_ROUTE = re.compile(r"\.route\(\s*\"([^\"]+)\"\s*,\s*([^)]*\))")
MAIN_FN = {
    "rs": re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+main\s*\("),
    "cpp": re.compile(r"^\s*(?:int|auto|void)\s+main\s*\("),
    "go": re.compile(r"^func\s+main\s*\("),
    "py": re.compile(r"^if\s+__name__\s*==\s*['\"]__main__['\"]"),
}
ENTRY_DIR_TAGS = [
    ("/Console/Commands/", "COMMAND"), ("/Jobs/", "JOB"), ("/Listeners/", "LISTENER"),
    ("/Events/", "EVENT"), ("/Mail/", "MAIL"), ("/Notifications/", "NOTIFICATION"),
    ("/Webhooks/", "WEBHOOK"), ("/Middleware/", "MIDDLEWARE"), ("/Policies/", "POLICY"),
    ("/src/bin/", "BINARY"),
]
NEXT_PAGE = re.compile(r"(^|/)app/(.*/)?(page|route|layout)\.(tsx|ts|jsx|js)$")
NEXT_PAGES_API = re.compile(r"(^|/)pages/(api/.*)\.(tsx|ts|jsx|js)$")
# plain PHP (no framework): front controllers and hand-written path checks
PHP_FRONT = re.compile(r"\$_SERVER\[\s*['\"](REQUEST_URI|PATH_INFO)['\"]\s*\]")
PHP_PATH_CHECK = re.compile(
    r"\$\w*(?:path|uri|route|url)\w*\s*(?:===|!==|==|!=)\s*['\"](/[^'\"]*)['\"]"
    r"|['\"](/[^'\"]*)['\"]\s*(?:===|!==|==|!=)\s*\$\w*(?:path|uri|route|url)\w*"
    r"|^\s*case\s+['\"](/[^'\"]*)['\"]\s*:", re.I)
PHP_CLI_HINT = re.compile(r"\$argv\b|PHP_SAPI\s*===?\s*['\"]cli['\"]|php_sapi_name\(\)|STDIN|STDOUT")
# client code calling the backend
JS_API_CALL = re.compile(r"\b(fetch|axios\.(get|post|put|patch|delete)|\$http\.(get|post|put|patch|delete))\(\s*[`'\"](/[^`'\"?$]*)")
DOCKER_CMD = re.compile(r"^\s*(ENTRYPOINT|CMD)\s+(.+)$")


def clean_handler(h):
    h = (h or "").replace("::class", "")
    m = re.match(r"\s*\[\s*([\w\\]+)\s*,\s*['\"](\w+)['\"]\s*\]", h)
    if m:
        return f"{m.group(1).split(chr(92))[-1]}@{m.group(2)}"
    return clip(h, 70).strip(" ,")


def scan_entries(rel, lines, lang, entries):
    main_rx = MAIN_FN.get("cpp" if lang == "cpph" else lang)
    if lang == "php":
        text = "\n".join(lines)
        if PHP_FRONT.search(text):
            entries.append(f"FRONT CONTROLLER {rel} (routes requests by URL path)")
        elif (("/" not in rel or rel.split("/")[0] in ("bin", "scripts", "script", "cli", "console"))
              and not re.search(r"^\s*(?:final\s+|abstract\s+)?(?:class|interface|trait|enum)\s+\w+", text, re.M)
              and (PHP_CLI_HINT.search(text) or re.search(r"^\s*(?:require|include)(?:_once)?\b", text, re.M))):
            entries.append(f"CLI SCRIPT {rel} (run: php {rel})")
    for i, line in enumerate(lines, 1):
        if main_rx and main_rx.search(line):
            entries.append(f"MAIN {rel}:{i}")
        if lang == "php":
            m = PHP_PATH_CHECK.search(line)
            if m:
                entries.append(f"ROUTE {m.group(1) or m.group(2) or m.group(3)} (path check)  ({rel}:{i})")
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
            m = JS_API_CALL.search(line)
            if m:
                entries.append(f"CLIENT CALL {m.group(1)} {m.group(4)}  ({rel}:{i})")
        elif lang == "py":
            m = FLASK_ROUTE.search(line)
            if m:
                entries.append(f"ROUTE {m.group(1).upper()} {m.group(2)}  ({rel}:{i})")
        elif lang == "rs":
            m = RUST_ATTR_ROUTE.search(line)
            if m:
                entries.append(f"ROUTE {m.group(1).upper()} {m.group(2)}  ({rel}:{i})")
            m = RUST_AXUM_ROUTE.search(line)
            if m:
                entries.append(f"ROUTE {m.group(1)} → {clip(m.group(2), 50)}  ({rel}:{i})")


def regex_symbols(lines, lang):
    symbols = []
    rules = RULES.get(lang, [])
    for i, line in enumerate(lines, 1):
        if len(symbols) >= MAX_SYMBOLS_PER_FILE:
            break
        for rx, fmt, member in rules:
            m = rx.match(line)
            if not m:
                continue
            text_out = fmt(m)
            if not text_out:
                break
            if member is None:
                is_member = bool(line[: len(line) - len(line.lstrip())])
            else:
                is_member = member
            symbols.append((1 if is_member else 0, text_out, i))
            break
    return symbols


# ---------------------------------------------------------------- tree-sitter engine (optional)
# Node types that define symbols, per grammar. Value: label. Containers get members indented.
TS_DEFS = {
    "rust": {"function_item": "fn", "function_signature_item": "fn", "struct_item": "struct", "enum_item": "enum",
             "trait_item": "trait", "impl_item": "impl", "mod_item": "mod", "type_item": "type",
             "union_item": "union", "macro_definition": "macro_rules!"},
    "cpp": {"function_definition": "", "class_specifier": "class", "struct_specifier": "struct",
            "union_specifier": "union", "enum_specifier": "enum", "namespace_definition": "namespace",
            "field_declaration": "", "declaration": ""},
    "c": {"function_definition": "", "struct_specifier": "struct", "union_specifier": "union",
          "enum_specifier": "enum", "declaration": ""},
    "go": {"function_declaration": "func", "method_declaration": "func", "type_spec": "type"},
    "python": {"function_definition": "def", "class_definition": "class"},
    "typescript": {"function_declaration": "function", "class_declaration": "class",
                   "abstract_class_declaration": "class", "method_definition": "", "interface_declaration": "interface",
                   "type_alias_declaration": "type", "enum_declaration": "enum", "variable_declarator": "const"},
    "php": {"class_declaration": "class", "interface_declaration": "interface", "trait_declaration": "trait",
            "enum_declaration": "enum", "function_definition": "function", "method_declaration": ""},
    "java": {"class_declaration": "class", "interface_declaration": "interface", "enum_declaration": "enum",
             "record_declaration": "record", "method_declaration": "", "constructor_declaration": ""},
    "kotlin": {"class_declaration": "class", "object_declaration": "object", "function_declaration": "fun"},
    "csharp": {"class_declaration": "class", "interface_declaration": "interface", "struct_declaration": "struct",
               "enum_declaration": "enum", "record_declaration": "record", "method_declaration": "",
               "constructor_declaration": ""},
    "ruby": {"class": "class", "module": "module", "method": "def", "singleton_method": "def"},
}
TS_DEFS["tsx"] = TS_DEFS["typescript"]
TS_DEFS["javascript"] = TS_DEFS["typescript"]
TS_FUNCTION_KINDS = {"function_item", "function_definition", "function_declaration", "method_declaration",
                     "method_definition", "constructor_declaration", "method", "singleton_method",
                     "function_signature_item"}
TS_NAMESPACE_KINDS = {"namespace_definition", "module"}


class TreeSitterEngine:
    def __init__(self):
        import tree_sitter_language_pack as tslp  # optional dependency
        self.tslp = tslp
        self.parsers = {}

    def parser(self, grammar):
        if grammar not in self.parsers:
            try:
                self.parsers[grammar] = self.tslp.get_parser(grammar)
            except Exception:
                self.parsers[grammar] = None  # e.g. grammar download blocked -> regex fallback
        return self.parsers[grammar]

    # NOTE: line numbers come from byte offsets, and names from slicing our own source bytes.
    # Node.start_point and Node.text are avoided on purpose: in tree-sitter-language-pack 1.22.x
    # touching start_point corrupted memory and crashed the interpreter intermittently.
    @staticmethod
    def _row(node, line_starts):
        import bisect
        return bisect.bisect_right(line_starts, node.start_byte)

    def _keep(self, node, grammar, src):
        t = node.type
        if t in ("struct_specifier", "class_specifier", "union_specifier", "enum_specifier"):
            return node.child_by_field_name("body") is not None
        if t in ("declaration", "field_declaration"):
            # only function prototypes in headers / class bodies
            decl = node.child_by_field_name("declarator")
            return decl is not None and decl.type == "function_declarator"
        if t == "variable_declarator":
            val = node.child_by_field_name("value")
            return val is not None and val.type in ("arrow_function", "function_expression", "function")
        return True

    def _signature(self, node, label, src):
        if node.type == "macro_definition":
            name = node.child_by_field_name("name")
            nm = src[name.start_byte:name.end_byte].decode("utf-8", "ignore") if name is not None else "?"
            return f"macro_rules! {nm}"
        body = node.child_by_field_name("body")
        if body is not None:
            text = src[node.start_byte:body.start_byte].decode("utf-8", "ignore")
        else:
            text = src[node.start_byte:node.end_byte].decode("utf-8", "ignore")
            if node.type != "variable_declarator":
                text = text.split("\n")[0]
        if node.type == "variable_declarator":
            text = text.split("=>")[0] + "=>"
        text = text.split("\n{")[0].rstrip(" \t\n{;=:")
        text = re.sub(r"\s+", " ", text).strip()
        if label and not re.match(rf"^(\S+\s+)*{re.escape(label)}\b", text):
            text = f"{label} {text}"
        return clip(text, 110)

    def symbols(self, rel, src_bytes, grammar):
        parser = self.parser(grammar)
        if parser is None:
            return None
        tree = parser.parse(src_bytes)
        defs = TS_DEFS.get(grammar, {})
        out = []
        line_starts = [0] + [i + 1 for i, b in enumerate(src_bytes) if b == 10]

        def walk(node, depth):
            if len(out) >= MAX_SYMBOLS_PER_FILE:
                return
            for child in node.children:
                t = child.type
                if t in defs and self._keep(child, grammar, src_bytes):
                    out.append((min(depth, 1), self._signature(child, defs[t], src_bytes),
                                self._row(child, line_starts)))
                    if t in TS_FUNCTION_KINDS or t == "variable_declarator":
                        continue  # never descend into function bodies
                    walk(child, depth if t in TS_NAMESPACE_KINDS else depth + 1)
                else:
                    walk(child, depth)

        walk(tree.root_node, 0)
        return out


# ---------------------------------------------------------------- build
def build(root, max_chars, includes, engine_name):
    files = list_files(root, includes)
    head = run_git(root, "rev-parse", "--short", "HEAD").strip() or "none"
    ts_engine = None
    if engine_name in ("auto", "tree-sitter"):
        try:
            ts_engine = TreeSitterEngine()
        except ImportError:
            if engine_name == "tree-sitter":
                sys.exit("tree-sitter engine requested but not installed: pip install tree-sitter-language-pack")
    used = collections.Counter()
    entries, per_file = [], []
    dir_counts = collections.Counter()
    for rel in files:
        ext = os.path.splitext(rel)[1].lower()
        lang = EXT_LANG[ext]
        try:
            with open(os.path.join(root, rel), "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        text = raw.decode("utf-8", errors="ignore")
        lines = text.splitlines()
        parts = rel.split("/")
        dir_counts["/".join(parts[:2]) if len(parts) > 2 else (parts[0] if len(parts) > 1 else ".")] += 1
        if NEXT_PAGE.search(rel) or NEXT_PAGES_API.search(rel):
            entries.append(f"PAGE/ROUTE {rel}")
        for frag, tag in ENTRY_DIR_TAGS:
            if frag in "/" + rel:
                entries.append(f"{tag} {rel}")
                break
        scan_entries(rel, lines, lang, entries)
        symbols = None
        if ts_engine is not None and ext in EXT_TS:
            try:
                symbols = ts_engine.symbols(rel, raw, EXT_TS[ext])
            except Exception:
                symbols = None
            if symbols is not None:
                used["tree-sitter"] += 1
        if symbols is None:
            symbols = regex_symbols(lines, lang)
            used["regex"] += 1
        per_file.append((rel, len(lines), symbols))

    # container start commands (Dockerfile ENTRYPOINT / CMD)
    for rel in run_git(root, "ls-files").splitlines():
        base = rel.rsplit("/", 1)[-1]
        if not (base.startswith("Dockerfile") or base.endswith(".Dockerfile")):
            continue
        if includes and not any(rel.startswith(i.rstrip("/") + "/") for i in includes):
            continue
        try:
            with open(os.path.join(root, rel), encoding="utf-8", errors="ignore") as fh:
                for i, line in enumerate(fh, 1):
                    m = DOCKER_CMD.match(line)
                    if m:
                        entries.append(f"CONTAINER {m.group(1)} {clip(m.group(2), 70)}  ({rel}:{i})")
        except OSError:
            pass

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    engines = ", ".join(f"{k}: {v} files" for k, v in sorted(used.items())) or "none"
    header = [
        "# Code skeleton",
        "",
        f"Generated: {now} · Generated at commit: {head} · Files mapped: {len(per_file)} · Engine: {engines}",
        "Generated by the refresh-skeleton skill. Line numbers point to definitions: read only the ranges",
        "you need. Search this file with grep instead of reading it whole. Regex results are approximate.",
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
    return text, len(per_file), len(entries), mode, engines


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=os.environ.get("CLAUDE_PROJECT_DIR", "."))
    ap.add_argument("--out", default=None, help="output path (default: <root>/.ai/context/skeleton.md)")
    ap.add_argument("--max-chars", type=int, default=60000)
    ap.add_argument("--include", action="append", default=[], help="only map this directory (repeatable)")
    ap.add_argument("--engine", choices=["auto", "regex", "tree-sitter"], default="auto")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    out = a.out or os.path.join(root, ".ai", "context", "skeleton.md")
    text, nfiles, nentries, mode, engines = build(root, a.max_chars, [i.strip("./") for i in a.include], a.engine)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"Wrote {os.path.relpath(out, root)}: {nfiles} files, {nentries} entry points, "
          f"{len(text):,} chars, mode: {mode}, engine: {engines}")


if __name__ == "__main__":
    sys.exit(main())
