#!/usr/bin/env python3
"""Task readiness: is a task written well enough to start work?

  readiness.py new T-031 --type bug --title "Partial refund fails" [--risk high]
  readiness.py check [T-031 | path/to/spec.md] [--json]   score the task spec, save a record
  readiness.py verify [T-031] [--json]                    is the latest record still bound to the spec?
  readiness.py trace [T-031] [--json]                     which acceptance criteria have a test?
  readiness.py status

A task spec lives at .ai/specs/<T-id>/spec.md. Its type decides what it must contain:

  feature   why, what, testable acceptance criteria (should: out of scope, edge cases, ...)
  bug       steps to reproduce, expected vs actual, environment (should: evidence, impact)
  change    why, what must not change, acceptance criteria
  refactor  why, "behaviour stays the same", the tests that already cover it
  chore     what and why

Every type: no open [NEEDS CLARIFICATION] markers; high-risk tasks need a rollback plan.

Scoring, cheapest and most reliable first:
  1. Is each item present (not empty, not a placeholder or TBD)?
  2. Is it good enough? Acceptance criteria must be checkable (Given/When/Then or a measurable
     result, no vague words like "fast"); every FR-xxx needs an acceptance criterion; bug steps
     must be numbered actions; expected and actual must differ.
  3. Optional: the decision-gate model (laya / vega / Jev) judges whether the criteria cover the
     goal or the bug can be reproduced. It can only lower the verdict, never raise it.

Verdicts: ready (score >= 80, every must-have item ok, no open clarifications), needs_info
(ask at most 5 questions, then check again), not_ready (score < 50).
Modes (.ai/readiness.json): off, advisory (default: report only), required (the pre-tool guard
refuses edits to source files until the current task is ready).

Standard library only (Python 3.8+). Records: .ai/review/readiness/<T-id>.json.
"""
import argparse
import copy
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

READINESS_VERSION = "1"
READY, NEEDS_INFO, NOT_READY, OFF = "ready", "needs_info", "not_ready", "off"
MODES = ("off", "advisory", "required")
TYPES = ("feature", "bug", "change", "refactor", "chore")
RISKS = ("low", "normal", "high")
CONFIG_REL = os.path.join(".ai", "readiness.json")
SPECS_REL = os.path.join(".ai", "specs")
RECORDS_REL = os.path.join(".ai", "review", "readiness")
TASK_ID = re.compile(r"^T-\d{1,6}$")
MAX_QUESTIONS = 5

DEFAULT_CONFIG = {
    "mode": "advisory",
    "ready_score": 80,
    "ask_score": 50,
    "model": {"enabled": False, "min_confidence": 0.7},
    "skip": {},  # {"item_id": "reason"}: drop an item for this project, e.g. {"reviewers": "solo project"}
}

# --------------------------------------------------------------------------- spec layout
# Each section: (heading, hint shown in a new spec). Headings are matched case-insensitively.
SECTION_HINTS = {
    "Why": "Who is this for, and what problem does it solve? Link the ticket if there is one.",
    "What": "What will change, in a few lines. Name the screens, endpoints, jobs or modules.",
    "Out of scope": "What this task deliberately does not do.",
    "Requirements": "Numbered: - FR-001: The system MUST ...",
    "Acceptance criteria": ("One per line, each checkable and tied to a requirement:\n"
                            "- AC-001 (FR-001): Given ... When ... Then ...\n"
                            "Name or comment each test with the AC id it proves (e.g. test_ac_001_...)."),
    "Steps to reproduce": "Numbered actions someone else can follow:\n1. ...\n2. ...",
    "Expected": "What should happen.",
    "Actual": "What happens instead. Paste the exact error text.",
    "Environment": "Where it happens: environment (local / staging / prod), app version or commit, browser or OS.",
    "Evidence": "Error message, log line, stack trace, screenshot path, or request id.",
    "Impact": "Who or what is affected, how often, since when.",
    "Must not change": "Behaviour, APIs, data or outputs that must stay exactly as they are.",
    "Existing tests": "The tests that already cover this code (the safety net), and how to run them.",
    "Edge cases": "Empty input, limits, duplicates, retries, time zones, currency rounding, permissions...",
    "Non-functional": "Performance, security, accessibility or compliance needs. Write 'none' if there are none.",
    "Dependencies and access": "Credentials, test data, external systems or people needed. Write 'none' if none.",
    "Rollback": "How to undo this safely if it goes wrong in production.",
    "Reviewers": "Who must review this before merge.",
    "Open questions": "Unresolved questions. Mark blocking ones: [NEEDS CLARIFICATION: ...]",
    "Answers": "Answers to readiness questions, with dates.",
    "Tasks": "Implementation steps as checkboxes: - [ ] 1. ...",
    "Convergence": "Filled by the converge skill after implementation.",
}

SECTIONS_BY_TYPE = {
    "feature": ["Why", "What", "Out of scope", "Requirements", "Acceptance criteria", "Edge cases",
                "Non-functional", "Dependencies and access"],
    "bug": ["Why", "Steps to reproduce", "Expected", "Actual", "Environment", "Evidence", "Impact",
            "Acceptance criteria", "Dependencies and access"],
    "change": ["Why", "What", "Must not change", "Out of scope", "Requirements", "Acceptance criteria",
               "Edge cases", "Dependencies and access"],
    "refactor": ["Why", "What", "Must not change", "Existing tests", "Acceptance criteria"],
    "chore": ["Why", "What"],
}
HIGH_RISK_SECTIONS = ["Rollback", "Reviewers"]
COMMON_TAIL = ["Open questions", "Answers", "Tasks", "Convergence"]

# Checklist items: id -> definition. "level" is must or should; weight sets the score.
# "types" lists the task types it applies to; "high_risk" items apply only when risk is high.
ITEMS = {
    "why": {"label": "why", "sections": ["why"], "level": "must", "weight": 15,
            "types": TYPES, "question": "Why is this needed: who is it for and what problem does it solve?"},
    "what": {"label": "what changes (scope)", "sections": ["what", "scope"], "level": "must", "weight": 15,
             "types": ("feature", "change", "refactor", "chore"),
             "question": "What exactly should change? Name the screens, endpoints, jobs or modules."},
    "acceptance": {"label": "acceptance criteria", "sections": ["acceptance criteria"], "weight": 20,
                   "level": {"feature": "must", "change": "must", "refactor": "must", "bug": "should"},
                   "types": ("feature", "bug", "change", "refactor"),
                   "question": ("How will we know it works? Give acceptance criteria as "
                                "'Given ... When ... Then ...' with a concrete result.")},
    "fr_coverage": {"label": "every requirement has an acceptance criterion", "sections": ["requirements"],
                    "level": "should", "weight": 10, "types": ("feature", "change"),
                    "question": "Which acceptance criterion proves each requirement?",
                    "question_missing": ("What must the system do? List the requirements as "
                                         "'FR-001: The system MUST ...'.")},
    "out_of_scope": {"label": "out of scope", "sections": ["out of scope"], "level": "should", "weight": 5,
                     "types": ("feature", "change"), "allow_none": True,
                     "question": "Is there anything this task should deliberately not do?"},
    "edge_cases": {"label": "edge cases", "sections": ["edge cases"], "level": "should", "weight": 5,
                   "types": ("feature", "change"), "allow_none": True,
                   "question": ("Which edge cases matter (empty input, limits, duplicates/retries, time zones, "
                                "rounding, permissions)?")},
    "non_functional": {"label": "non-functional needs", "sections": ["non-functional"], "level": "should",
                       "weight": 5, "types": ("feature",), "allow_none": True,
                       "question": "Any performance, security or compliance needs? ('none' is a fine answer)"},
    "must_not_change": {"label": "what must not change", "sections": ["must not change"], "level": "must",
                        "weight": 15, "types": ("change", "refactor"),
                        "question": "What behaviour, API or data must stay exactly as it is?"},
    "safety_net": {"label": "existing tests (safety net)", "sections": ["existing tests", "safety net"],
                   "level": "must", "weight": 10, "types": ("refactor",),
                   "question": "Which existing tests cover this code, and do they pass today?"},
    "steps": {"label": "steps to reproduce", "sections": ["steps to reproduce"], "level": "must", "weight": 20,
              "types": ("bug",), "question": "What are the exact steps to reproduce it, as numbered actions?"},
    "expected": {"label": "expected result", "sections": ["expected", "expected result"], "level": "must",
                 "weight": 10, "types": ("bug",), "question": "What should happen instead?"},
    "actual": {"label": "actual result", "sections": ["actual", "actual result"], "level": "must",
               "weight": 10, "types": ("bug",),
               "question": "What actually happens? Paste the exact error text if there is one."},
    "environment": {"label": "environment / version", "sections": ["environment"], "level": "must",
                    "weight": 10, "types": ("bug",),
                    "question": "Which environment and app version (or commit) did this happen on?"},
    "evidence": {"label": "evidence (error, log, trace)", "sections": ["evidence"], "level": "should",
                 "weight": 8, "types": ("bug",),
                 "question": "Can you paste the exact error message, log line or stack trace?"},
    "impact": {"label": "impact", "sections": ["impact"], "level": "should", "weight": 5, "types": ("bug",),
               "question": "Who or what is affected, how often, and since when?"},
    "dependencies": {"label": "dependencies and access", "sections": ["dependencies and access", "dependencies"],
                     "level": "should", "weight": 5, "types": ("feature", "bug", "change"), "allow_none": True,
                     "question": ("Are any credentials, test data, external systems or people needed? "
                                  "('none' is a fine answer)")},
    "rollback": {"label": "rollback plan", "sections": ["rollback"], "level": "must", "weight": 10,
                 "types": TYPES, "high_risk": True,
                 "question": "How do we undo this safely if it goes wrong in production?"},
    "reviewers": {"label": "reviewers", "sections": ["reviewers"], "level": "should", "weight": 5,
                  "types": TYPES, "high_risk": True, "question": "Who must review this before it is merged?"},
}

PLACEHOLDER = re.compile(r"^\s*(?:[-*+]|\d+[.)])?\s*(?:\.\.\.|…|tbd|todo|tbc|\?+|xxx|fill in.*|"
                         r"\[[^\]]*\]|\(.*\))?\s*$", re.I)
NONE_ANSWER = re.compile(r"^\s*(?:[-*+]\s*)?(none|n/?a|nothing|not needed|no)\b", re.I)
VAGUE = re.compile(r"\b(fast|faster|quick(?:ly)?|slow|user[- ]friendly|intuitive|easy|easily|simple|nice|"
                   r"better|good|properly|correctly|appropriate(?:ly)?|robust|seamless(?:ly)?|efficient(?:ly)?|"
                   r"as expected|works?|etc\.?|and so on|reasonable|optimal|clean)\b", re.I)
MEASURABLE = re.compile(r"\d|\"[^\"]+\"|'[^']+'|`[^`]+`|\b(returns?|shows?|displays?|equals?|is (?:not )?"
                        r"(?:shown|stored|sent|saved|created|deleted|rejected|accepted|visible|hidden|empty|null)|"
                        r"responds?|status|error|redirects?|appears?|contains?|matches?|rejects?|blocks?|"
                        r"logs?|emails?|exports?|records?|within|at most|at least|no more than|exactly|unchanged)\b",
                        re.I)
GWT = re.compile(r"\bgiven\b.*\bwhen\b.*\bthen\b", re.I | re.S)
CLARIFY = re.compile(r"\[NEEDS CLARIFICATION[^\]]*\]", re.I)
FR_ID = re.compile(r"\bFR-(\d{1,4})\b", re.I)
AC_ID = re.compile(r"\bAC-(\d{1,4})\b", re.I)
SOURCE_SKIP_DIRS = {".git", ".ai", ".claude", "node_modules", "vendor", ".venv", "venv", "dist", "build", "target"}
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "testing", "e2e", "integration_tests"}
TEST_NAME = re.compile(
    r"(^test_.+\.py$|.+_test\.(py|go|rs|cc|cpp|c|rb)$|.+\.(test|spec)\.[cm]?[jt]sx?$|"
    r".+Tests?\.(php|java|kt|cs|swift)$|.+_spec\.rb$|^test_.+\.(c|cc|cpp)$)")


class ReadinessError(Exception):
    """A configuration or input problem the caller must fix (exit code 2)."""


# --------------------------------------------------------------------------- repository helpers
def find_root(start=None):
    start = start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    r = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"], capture_output=True, timeout=30)
    if r.returncode == 0:
        return r.stdout.decode().strip()
    if os.path.isdir(os.path.join(start, ".ai")):
        return os.path.abspath(start)
    raise ReadinessError("run this inside the repository (no git repo or .ai/ folder at %s)" % start)


def current_task(root):
    """The task id from the 'Current task' line of .ai/memory/state.md, or ''."""
    try:
        with open(os.path.join(root, ".ai", "memory", "state.md"), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return ""
    m = re.search(r"\*\*Current task\*\*\s*:\s*(T-\d{1,6})\b", text)
    return m.group(1) if m else ""


def spec_path(root, task_id):
    return os.path.join(root, SPECS_REL, task_id, "spec.md")


def resolve_spec(root, arg=None):
    """(task_id, path) from a task id, a path, or the current task in state.md."""
    if arg and (arg.endswith(".md") or os.sep in arg or "/" in arg):
        path = arg if os.path.isabs(arg) else os.path.join(root, arg)
        meta = parse_front_matter(read_file(path))[0] if os.path.exists(path) else {}
        task = meta.get("id") or os.path.basename(os.path.dirname(path))
        return task, path
    task = (arg or current_task(root)).strip()
    if not task:
        raise ReadinessError("no task given and no 'Current task: T-###' line in .ai/memory/state.md")
    if not TASK_ID.match(task):
        raise ReadinessError("task id must look like T-031, got %r" % task)
    return task, spec_path(root, task)


def read_file(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------------------- config
def load_config(root):
    path = os.path.join(root, CONFIG_REL)
    user = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                user = json.load(fh)
        except (OSError, ValueError) as exc:
            raise ReadinessError("%s is not valid JSON: %s" % (CONFIG_REL, exc))
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    for k, v in user.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k] = dict(cfg[k], **{kk: vv for kk, vv in v.items() if not kk.startswith("_")})
        else:
            cfg[k] = v
    env_mode = os.environ.get("GOD_READINESS_MODE", "").strip().lower()
    if env_mode:
        cfg["mode"] = env_mode
    if cfg["mode"] not in MODES:
        raise ReadinessError("mode must be one of %s, got %r" % ("/".join(MODES), cfg["mode"]))
    for key in ("ready_score", "ask_score"):
        try:
            cfg[key] = float(cfg[key])
        except (TypeError, ValueError):
            raise ReadinessError("%s must be a number" % key)
    if not 0 <= cfg["ask_score"] <= cfg["ready_score"] <= 100:
        raise ReadinessError("need 0 <= ask_score <= ready_score <= 100")
    unknown = [k for k in cfg.get("skip") or {} if k not in ITEMS]
    if unknown:
        raise ReadinessError("skip lists unknown items: %s (known: %s)" % (", ".join(unknown), ", ".join(ITEMS)))
    return cfg


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- parsing
def parse_front_matter(text):
    """Simple 'key: value' front matter between --- lines. Returns (meta, body)."""
    meta = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].splitlines():
                line = line.split("#", 1)[0].strip()
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip().strip("\"'")
            text = text[end + 4:]
    return meta, text


def strip_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def parse_sections(body):
    """Flat {normalised heading: text} for every ## and ### heading."""
    sections, current, buf = {}, None, []
    for line in strip_comments(body).splitlines():
        m = re.match(r"^\s{0,3}#{2,4}\s+(.+?)\s*#*\s*$", line)
        if m:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = normalise_heading(m.group(1))
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def normalise_heading(h):
    h = re.sub(r"\(.*?\)", "", h)  # "Bug report (bugs only)" -> "bug report"
    h = re.sub(r"[-_/]", " ", h)    # "Non-functional" == "Non functional"
    return re.sub(r"\s+", " ", h.strip(" :").lower()).strip()


def meaningful_lines(text):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip() and not PLACEHOLDER.match(ln)]


def section_text(sections, names):
    for n in names:
        n = normalise_heading(n)
        if n in sections:
            return sections[n]
    return None


def list_items(text):
    """Bullet or numbered lines (continuation lines are joined to their item)."""
    items = []
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line):
            items.append(re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line).strip())
        elif line.strip() and items and raw.startswith((" ", "\t")):
            items[-1] += " " + line.strip()
        elif line.strip():
            items.append(line.strip())
    return [i for i in items if i and not PLACEHOLDER.match(i)]


# --------------------------------------------------------------------------- checks
def ac_is_testable(ac):
    """(ok, reason). A criterion is checkable if it is Given/When/Then or names a measurable result."""
    text = re.sub(r"^AC-\d+\s*(\([^)]*\))?\s*:?\s*", "", ac, flags=re.I)
    if len(text) < 12:
        return False, "too short to check"
    vague = VAGUE.findall(text)
    gwt = bool(GWT.search(text))
    measurable = bool(MEASURABLE.search(text))
    if vague and not measurable:
        return False, "vague (%s) with nothing measurable" % ", ".join(sorted({v.lower() for v in vague}))
    if not gwt and not measurable:
        return False, "no observable result (use Given/When/Then or a concrete value)"
    return True, ""


def evaluate_item(item_id, item, sections, meta):
    """Return (status, message) where status is ok, weak or missing."""
    text = section_text(sections, item["sections"])
    lines = meaningful_lines(text)
    if item_id == "fr_coverage":
        frs = sorted({int(n) for n in FR_ID.findall(text or "")})
        if not frs:
            if not lines:
                return "missing", "no requirements listed (- FR-001: The system MUST ...)"
            return "weak", "number the requirements (FR-001: ...) so each can be traced to a criterion"
        ac_text = section_text(sections, ["acceptance criteria"]) or ""
        covered = set()
        for ac in list_items(ac_text):
            covered |= {int(n) for n in FR_ID.findall(ac)}
        missing = [n for n in frs if n not in covered]
        if missing:
            return "weak", "no acceptance criterion for %s" % ", ".join("FR-%03d" % n for n in missing)
        return "ok", "%d requirement(s), all covered" % len(frs)
    if not lines:
        return "missing", "empty or only placeholders"
    joined = " ".join(lines)
    if item.get("allow_none") and NONE_ANSWER.match(lines[0]) and len(lines) == 1:
        return "ok", "explicitly none"
    if item_id == "acceptance":
        acs = list_items(text)
        bad = []
        for i, ac in enumerate(acs, 1):
            ok, why = ac_is_testable(ac)
            if not ok:
                m = AC_ID.search(ac)
                bad.append("%s: %s" % ("AC-%03d" % int(m.group(1)) if m else "#%d" % i, why))
        if bad:
            return "weak", "; ".join(bad[:4]) + (" (+%d more)" % (len(bad) - 4) if len(bad) > 4 else "")
        return "ok", "%d checkable criteria" % len(acs)
    if item_id == "steps":
        steps = [ln for ln in (text or "").splitlines() if re.match(r"^\s*\d+[.)]\s+\S", ln)]
        steps = [s for s in steps if not PLACEHOLDER.match(s)]
        if len(steps) < 2:
            return "weak", "write the steps as at least 2 numbered actions (1. ... 2. ...)"
        return "ok", "%d steps" % len(steps)
    if item_id == "actual":
        expected = " ".join(meaningful_lines(section_text(sections, ITEMS["expected"]["sections"])))
        if expected and expected.lower() == joined.lower():
            return "weak", "actual is the same as expected"
        if re.search(r"^\s*(it )?(doesn'?t|does not|isn'?t) work\.?\s*$|^\s*(it )?(errors?|fails?|broken)\.?\s*$",
                     joined, re.I):
            return "weak", "say what happens exactly (error text, wrong value)"
        return "ok", ""
    if item_id == "evidence":
        if len(joined) < 15 or re.match(r"^\s*(it )?(errors?|fails?|crash(es)?)\.?\s*$", joined, re.I):
            return "weak", "paste the exact error text, log line or stack trace"
        return "ok", ""
    if item_id in ("why", "what", "must_not_change", "environment", "rollback") and len(joined) < 12:
        return "weak", "too short to act on"
    return "ok", ""


def applicable_items(task_type, risk, cfg):
    out = []
    for item_id, item in ITEMS.items():
        if task_type not in item["types"] or item_id in (cfg.get("skip") or {}):
            continue
        if item.get("high_risk") and risk != "high":
            continue
        level = item["level"][task_type] if isinstance(item["level"], dict) else item["level"]
        out.append((item_id, item, level))
    return out


def score_spec(text, cfg):
    """Deterministic layers 1 and 2. Returns a result dict (no I/O)."""
    meta, body = parse_front_matter(text)
    task_type = (meta.get("type") or "").lower()
    risk = (meta.get("risk") or "normal").lower()
    problems = []
    if task_type not in TYPES:
        problems.append("front matter 'type' must be one of %s (got %r)" % (", ".join(TYPES), task_type or ""))
    if risk not in RISKS:
        problems.append("front matter 'risk' must be one of %s (got %r)" % (", ".join(RISKS), risk))
    if problems:
        return {"type": task_type, "risk": risk, "score": 0, "verdict": NOT_READY, "items": [],
                "blockers": problems, "questions": [], "title": meta.get("title", "")}
    sections = parse_sections(body)
    items, total, earned = [], 0.0, 0.0
    for item_id, item, level in applicable_items(task_type, risk, cfg):
        status, message = evaluate_item(item_id, item, sections, meta)
        w = float(item["weight"])
        total += w
        earned += w if status == "ok" else (w / 2 if status == "weak" else 0.0)
        items.append({"id": item_id, "label": item["label"], "level": level, "status": status,
                      "message": message, "weight": w,
                      "question": item.get("question_missing", item["question"]) if status == "missing"
                      else item["question"]})
    score = round(100.0 * earned / total) if total else 0
    clarifications = [m.group(0) for m in CLARIFY.finditer(strip_comments(body))]
    blockers = ["open clarification: %s" % c for c in clarifications]
    must_gaps = [i for i in items if i["level"] == "must" and i["status"] != "ok"]
    if score < cfg["ask_score"]:
        verdict = NOT_READY
    elif blockers or must_gaps or score < cfg["ready_score"]:
        verdict = NEEDS_INFO
    else:
        verdict = READY
    return {"type": task_type, "risk": risk, "title": meta.get("title", ""), "score": score, "verdict": verdict,
            "items": items, "blockers": blockers, "questions": build_questions(items, clarifications),
            "sections": sections}


def build_questions(items, clarifications):
    """At most MAX_QUESTIONS: open clarifications first, then must-haves, then by weight."""
    qs = []
    for c in clarifications:
        inner = re.sub(r"^\[NEEDS CLARIFICATION\s*:?\s*|\]$", "", c, flags=re.I).strip()
        qs.append(inner + ("?" if inner and not inner.endswith("?") else "") if inner else
                  "Resolve the open [NEEDS CLARIFICATION] marker.")
    gaps = [i for i in items if i["status"] != "ok"]
    gaps.sort(key=lambda i: (i["level"] != "must", i["status"] != "missing", -i["weight"]))
    for i in gaps:
        q = i["question"]
        if i["status"] == "weak" and i["message"]:
            q = "%s (%s: %s)" % (q, i["label"], i["message"])
        qs.append(q)
    seen, out = set(), []
    for q in qs:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out[:MAX_QUESTIONS]


# --------------------------------------------------------------------------- optional model layer
MODEL_QUESTIONS = {
    "criteria_cover_goal": {
        "types": ("feature", "change", "refactor"),
        "instructions": ("Do the acceptance criteria, taken together, fully cover what the task says it must do "
                         "and why? Answer no if an important part of the goal has no criterion."),
        "pass_when": {"min": 0.5},
        "question": "Some of the goal may have no acceptance criterion: which outcome is not yet covered?",
    },
    "reproducible": {
        "types": ("bug",),
        "instructions": ("Could an engineer who has never seen this system reproduce the bug using only these "
                         "steps, the environment and the expected/actual results?"),
        "pass_when": {"min": 0.5},
        "question": "Could someone else reproduce this from the steps alone? Add the missing detail.",
    },
}


def load_gate_module():
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import decision_gate  # noqa: E402
    return decision_gate


def model_layer(root, cfg, result, spec_text):
    """Ask the decision-gate model. Returns (notes, extra_questions, failed). Never raises the verdict."""
    if not (cfg.get("model") or {}).get("enabled"):
        return [], [], False
    asked = {k: {"type": "noul", "instructions": q["instructions"]}
             for k, q in MODEL_QUESTIONS.items() if result["type"] in q["types"]}
    if not asked:
        return [], [], False
    try:
        gate = load_gate_module()
        gcfg = gate.load_config(root)
    except Exception as exc:
        return ["model check skipped: decision-gate config unavailable (%s)" % exc], [], False
    prov = gcfg["provider"]
    if not gate.is_local_url(prov["url"]) and gate.is_private_repo(root, gcfg) and \
            not prov.get("allow_remote_in_private_repo"):
        return ["model check refused: %s is remote and this repo is private" % prov["url"]], [], False
    text, _ = gate.scrub_secrets(strip_comments(spec_text))
    state = {"task_spec": text[:6000]}
    try:
        data, _ = gate.call_model(gcfg, state, asked)
    except gate.ModelUnavailable as exc:
        return ["model check unavailable: %s" % exc], [], False
    notes, extra, failed = [], [], False
    min_conf = float((cfg.get("model") or {}).get("min_confidence", 0.7))
    for qid in asked:
        try:
            norm = gate.normalize_answer("noul", data["answers"][qid])
        except (ValueError, KeyError) as exc:
            notes.append("model answer for %s is malformed (%s)" % (qid, exc))
            failed = True
            continue
        unsure = norm["abstain"] or norm["unbound"] or (norm["set_size"] or 0) > 1 or norm["confidence"] < min_conf
        passed = gate.rule_passes("noul", MODEL_QUESTIONS[qid]["pass_when"], norm["value"])
        if unsure or not passed:
            failed = True
            notes.append("model: %s %s (yes %.2f, confidence %.2f)" % (
                qid, "unsure" if unsure else "says no", norm["value"], norm["confidence"]))
            extra.append(MODEL_QUESTIONS[qid]["question"])
        else:
            notes.append("model: %s ok (yes %.2f)" % (qid, norm["value"]))
    return notes, extra, failed


# --------------------------------------------------------------------------- records
def records_dir(root):
    return os.path.join(root, RECORDS_REL)


def record_path(root, task_id):
    return os.path.join(records_dir(root), "%s.json" % task_id)


def write_record(root, task_id, record):
    d = records_dir(root)
    os.makedirs(d, exist_ok=True)
    path = record_path(root, task_id)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)
    return os.path.relpath(path, root).replace(os.sep, "/")


def load_record(root, task_id):
    try:
        with open(record_path(root, task_id), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def spec_digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def verify_record(root, task_id, record=None, cfg=None):
    """Problems that make the record stale (empty list = fresh)."""
    record = record if record is not None else load_record(root, task_id)
    if record is None:
        return ["no readiness record yet: run /task-ready %s" % task_id]
    path = spec_path(root, task_id) if not record.get("spec_path") else os.path.join(root, record["spec_path"])
    if not os.path.exists(path):
        return ["spec %s no longer exists" % os.path.relpath(path, root)]
    problems = []
    if spec_digest(path) != record.get("spec_sha256"):
        problems.append("the task spec changed since it was checked")
    cfg = cfg if cfg is not None else load_config(root)
    if digest(scoring_config(cfg)) != record.get("config_sha256"):
        problems.append("readiness config changed since the check")
    if record.get("readiness_version") != READINESS_VERSION:
        problems.append("record was written by a different readiness version")
    return problems


def scoring_config(cfg):
    """The parts of the config that change a verdict (mode does not)."""
    return {k: cfg[k] for k in ("ready_score", "ask_score", "model", "skip")}


def edit_check(root):
    """For the pre-tool guard: may source files be edited now? Returns (allowed, reason)."""
    cfg = load_config(root)
    if cfg["mode"] != "required":
        return True, ""
    task = current_task(root)
    if not task:
        return False, ("task readiness is in required mode and .ai/memory/state.md has no 'Current task: T-###': "
                       "register the task and run /task-ready first")
    record = load_record(root, task)
    if record is None:
        return False, "task %s has no readiness check yet: run /task-ready %s" % (task, task)
    if record.get("verdict") != READY:
        return False, "task %s is %s (score %s): answer its questions and run /task-ready again" % (
            task, record.get("verdict"), record.get("score"))
    problems = verify_record(root, task, record, cfg)
    if problems:
        return False, "task %s readiness record is stale (%s): run /task-ready again" % (task, "; ".join(problems))
    return True, ""


# --------------------------------------------------------------------------- trace (acceptance criteria -> tests)
def is_test_file(rel):
    parts = rel.replace("\\", "/").split("/")
    return any(p.lower() in TEST_DIRS for p in parts[:-1]) or bool(TEST_NAME.match(parts[-1]))


def repo_files(root):
    r = subprocess.run(["git", "-C", root, "ls-files", "-co", "--exclude-standard"], capture_output=True, timeout=60)
    if r.returncode == 0:
        return [p for p in r.stdout.decode("utf-8", "replace").splitlines() if p]
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SOURCE_SKIP_DIRS]
        out += [os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/") for f in files]
    return out


def ac_pattern(n):
    return re.compile(r"(?<![a-z0-9])ac[-_ ]?0*%d(?!\d)" % n, re.I)


def trace(root, task_id, spec_text):
    """Which acceptance criteria are named in at least one test file."""
    sections = parse_sections(parse_front_matter(spec_text)[1])
    acs = []
    for ac in list_items(section_text(sections, ["acceptance criteria"]) or ""):
        m = AC_ID.search(ac)
        if m:
            acs.append((int(m.group(1)), ac))
    tests = [p for p in repo_files(root) if is_test_file(p) and not p.startswith((".ai/", ".claude/"))]
    contents = {}
    for p in tests:
        try:
            with open(os.path.join(root, p), encoding="utf-8", errors="replace") as fh:
                contents[p] = fh.read()
        except OSError:
            continue
    covered, uncovered = [], []
    for n, text in acs:
        rx = ac_pattern(n)
        hits = sorted(p for p, c in contents.items() if rx.search(c) or rx.search(os.path.basename(p)))
        (covered if hits else uncovered).append({"id": "AC-%03d" % n, "text": text, "tests": hits[:5]})
    conv = (section_text(sections, ["convergence"]) or "")
    converged = bool(re.search(r"\bconverged\b", conv, re.I)) and not re.search(r"\bnot converged\b", conv, re.I)
    return {"task": task_id, "criteria": len(acs), "covered": covered, "uncovered": uncovered,
            "converged": converged, "open_tasks": len(re.findall(r"^\s*-\s*\[ \]", section_text(
                sections, ["tasks"]) or "", re.M))}


def spec_goal(spec_text, limit=2500):
    """A compact goal for the decision gate: title, why, what, requirements and acceptance criteria."""
    meta, body = parse_front_matter(spec_text)
    sections = parse_sections(body)
    parts = []
    if meta.get("title"):
        parts.append("%s (%s)" % (meta["title"], meta.get("type", "task")))
    for name in ("why", "what", "requirements", "acceptance criteria", "expected"):
        lines = meaningful_lines(section_text(sections, [name]) or "")
        if lines:
            parts.append("%s: %s" % (name.capitalize(), " ".join(lines)))
    text = "\n".join(parts)
    return text[:limit]


# --------------------------------------------------------------------------- commands
def new_spec_text(task_id, task_type, title, risk):
    lines = ["---", "id: %s" % task_id, "type: %s" % task_type, "title: %s" % title,
             "risk: %s            # low | normal | high (payments, auth, money, migrations, concurrency)" % risk,
             "status: draft", "---", "", "# %s · %s" % (task_id, title), ""]
    sections = SECTIONS_BY_TYPE[task_type] + (HIGH_RISK_SECTIONS if risk == "high" else []) + COMMON_TAIL
    for s in sections:
        lines += ["## %s" % s, "<!-- %s -->" % SECTION_HINTS[s].replace("\n", "\n     "), ""]
    return "\n".join(lines)


def cmd_new(args):
    root = find_root()
    if not TASK_ID.match(args.task):
        raise ReadinessError("task id must look like T-031, got %r" % args.task)
    path = spec_path(root, args.task)
    if os.path.exists(path) and not args.force:
        raise ReadinessError("%s already exists (use --force to replace it)" % os.path.relpath(path, root))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new_spec_text(args.task, args.type, args.title.strip(), args.risk))
    print("Created %s (%s, risk %s). Fill it in, then run: readiness.py check %s" % (
        os.path.relpath(path, root).replace(os.sep, "/"), args.type, args.risk, args.task))
    return 0


def run_check(root, arg=None):
    cfg = load_config(root)
    task, path = resolve_spec(root, arg)
    if cfg["mode"] == "off":
        return {"task": task, "verdict": OFF, "mode": "off"}, None
    if not os.path.exists(path):
        raise ReadinessError("no spec at %s: create it with  readiness.py new %s --type <%s> --title \"...\"" % (
            os.path.relpath(path, root), task, "|".join(TYPES)))
    text = read_file(path)
    result = score_spec(text, cfg)
    notes, extra, failed = model_layer(root, cfg, result, text) if result["items"] else ([], [], False)
    if failed and result["verdict"] == READY:
        result["verdict"] = NEEDS_INFO
    if extra:
        result["questions"] = (result["questions"] + [q for q in extra if q not in result["questions"]])[:MAX_QUESTIONS]
    record = {
        "readiness_version": READINESS_VERSION,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "task": task, "mode": cfg["mode"],
        "spec_path": os.path.relpath(path, root).replace(os.sep, "/"),
        "spec_sha256": spec_digest(path), "config_sha256": digest(scoring_config(cfg)),
        "type": result["type"], "risk": result["risk"], "title": result.get("title", ""),
        "score": result["score"], "verdict": result["verdict"],
        "items": result["items"], "blockers": result["blockers"], "questions": result["questions"],
        "model_notes": notes,
    }
    return record, write_record(root, task, record)


def print_check(rec, rel):
    if rec["verdict"] == OFF:
        print("Task readiness: OFF (set \"mode\" in .ai/readiness.json to advisory or required)")
        return
    print("Readiness %s (%s%s): %s/100 — %s   (mode: %s)" % (
        rec["task"], rec["type"] or "?", ", high risk" if rec.get("risk") == "high" else "", rec["score"],
        rec["verdict"].upper().replace("_", " "), rec["mode"]))
    marks = {"ok": "ok  ", "weak": "WEAK", "missing": "MISS"}
    for i in rec["items"]:
        msg = (" — " + i["message"]) if i["message"] and i["status"] != "ok" else (
            (" (%s)" % i["message"]) if i["message"] else "")
        print("  %s  %s%s%s" % (marks[i["status"]], i["label"], " [should]" if i["level"] == "should" else "", msg))
    for b in rec["blockers"]:
        print("  BLOCK %s" % b)
    for n in rec.get("model_notes") or []:
        print("  note  %s" % n)
    if rec["verdict"] != READY and rec["questions"]:
        print("Questions (%d):" % len(rec["questions"]))
        for k, q in enumerate(rec["questions"], 1):
            print("  %d. %s" % (k, q))
    if rel:
        print("Record: " + rel)


def cmd_check(args):
    root = find_root()
    rec, rel = run_check(root, args.task)
    if args.json:
        print(json.dumps(dict(rec, record_path=rel), indent=2, sort_keys=True))
    else:
        print_check(rec, rel)
    return 1 if rec.get("mode") == "required" and rec["verdict"] != READY else 0


def cmd_verify(args):
    root = find_root()
    task, _ = resolve_spec(root, args.task)
    rec = load_record(root, task)
    problems = verify_record(root, task, rec)
    ok = not problems and rec and rec.get("verdict") == READY
    if args.json:
        print(json.dumps({"task": task, "fresh": not problems, "verdict": (rec or {}).get("verdict"),
                          "problems": problems}, indent=2))
    else:
        print("Readiness %s: %s, %s" % (task, ((rec or {}).get("verdict") or "none").upper(),
                                       "fresh" if not problems else "STALE"))
        for p in problems:
            print("  - " + p)
    return 0 if ok else 1


def cmd_trace(args):
    root = find_root()
    task, path = resolve_spec(root, args.task)
    if not os.path.exists(path):
        raise ReadinessError("no spec at %s" % os.path.relpath(path, root))
    t = trace(root, task, read_file(path))
    if args.json:
        print(json.dumps(t, indent=2))
    else:
        print("Trace %s: %d/%d acceptance criteria named in a test; converged: %s; open tasks: %d" % (
            task, len(t["covered"]), t["criteria"], "yes" if t["converged"] else "no", t["open_tasks"]))
        for c in t["covered"]:
            print("  ok    %s  %s" % (c["id"], ", ".join(c["tests"])))
        for c in t["uncovered"]:
            print("  MISS  %s  %s" % (c["id"], c["text"][:90]))
    return 0 if not t["uncovered"] else 1


def cmd_status(args):
    root = find_root()
    cfg = load_config(root)
    task = current_task(root)
    print("Mode: %s (ready at %d, ask below that, not ready under %d)" % (cfg["mode"], cfg["ready_score"],
                                                                           cfg["ask_score"]))
    print("Model layer: %s" % ("on (decision-gate provider)" if cfg["model"].get("enabled") else "off"))
    if cfg.get("skip"):
        print("Skipped items: %s" % ", ".join("%s (%s)" % kv for kv in cfg["skip"].items()))
    print("Current task: %s" % (task or "none (set 'Current task' in .ai/memory/state.md)"))
    if task:
        rec = load_record(root, task)
        problems = verify_record(root, task, rec, cfg)
        print("Latest check: %s" % ("none" if rec is None else "%s %s/100, %s" % (
            rec["verdict"], rec["score"], "fresh" if not problems else "stale: " + "; ".join(problems))))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="readiness.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    n = sub.add_parser("new", help="create .ai/specs/<T-id>/spec.md for a task type")
    n.add_argument("task")
    n.add_argument("--type", required=True, choices=TYPES)
    n.add_argument("--title", required=True)
    n.add_argument("--risk", default="normal", choices=RISKS)
    n.add_argument("--force", action="store_true")
    c = sub.add_parser("check", help="score the task spec and save a record")
    c.add_argument("task", nargs="?")
    c.add_argument("--json", action="store_true")
    v = sub.add_parser("verify", help="is the latest record still bound to the spec?")
    v.add_argument("task", nargs="?")
    v.add_argument("--json", action="store_true")
    t = sub.add_parser("trace", help="which acceptance criteria are named in a test?")
    t.add_argument("task", nargs="?")
    t.add_argument("--json", action="store_true")
    sub.add_parser("status", help="mode, current task, latest check")
    args = ap.parse_args(argv)
    handlers = {"new": cmd_new, "check": cmd_check, "verify": cmd_verify, "trace": cmd_trace, "status": cmd_status}
    if args.cmd not in handlers:
        ap.print_help()
        return 2
    try:
        return handlers[args.cmd](args)
    except ReadinessError as exc:
        print("readiness error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
