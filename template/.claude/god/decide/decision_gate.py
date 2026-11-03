#!/usr/bin/env python3
"""Decision gate: a calibrated "is this change ready?" opinion from a typed-decision model,
asked only after the project's deterministic checks have passed.

  decision_gate.py check [--goal TEXT] [--base REF] [--skip-checks] [--json]
  decision_gate.py verify [--json]            is the latest receipt still bound to the current code?
  decision_gate.py status                     mode, provider, reachability, latest receipt
  decision_gate.py calibrate --data FILE      measure the model on labelled past diffs (JSONL)

Rules it enforces:
  1. Deterministic checks (tests, lint, types) run first. If any fails, the model is never asked.
  2. Uncertainty is not readiness: abstention, wide prediction sets, low confidence, timeouts,
     malformed or non-finite output, an unexpected model, or a truncated input can't yield "ready".
  3. Modes: off (does nothing), advisory (reports, never blocks), required (anything but "ready"
     fails; the publication guard denies git push / gh pr create without a fresh "ready" receipt).
  4. Every run writes a receipt bound to the base commit, the exact diff, the config and the model.
     Any change to those makes the receipt stale.
  5. No downloads here. The model server is set up and pinned separately.
  6. Benchmark accuracy is not code-review accuracy: `calibrate` measures the model on your own
     labelled diffs before you trust a threshold.
  7. When the current task has a spec (.ai/specs/<T-id>/spec.md, see readiness.py), its title, why and
     acceptance criteria become the goal, and an acceptance criterion that no test names caps the
     verdict at needs_review.

Speaks POST /v1/systemone, the wire protocol of TypeSafe Jev, laya-serve and vega_server.py.
Standard library only (Python 3.8+). Config: .ai/decision-gate.json. Receipts: .ai/review/receipts/.
"""
import argparse
import copy
import datetime
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

GATE_VERSION = "1"
READY, NEEDS_REVIEW, NOT_READY, UNAVAILABLE, OFF = "ready", "needs_review", "not_ready", "unavailable", "off"
MODES = ("off", "advisory", "required")
EXCLUDE = [":(exclude).ai", ":(exclude).claude"]
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
CONFIG_REL = os.path.join(".ai", "decision-gate.json")
RECEIPTS_REL = os.path.join(".ai", "review", "receipts")
MAX_UNTRACKED_BYTES = 200_000
KEEP_RECEIPTS = 50

DEFAULT_QUESTIONS = {
    "high_risk": {
        "type": "noul",
        "instructions": ("Does this change alter money or payment calculations, authentication or "
                         "authorization, data deletion, database schema or migrations, or concurrent or "
                         "background processing?"),
        "pass_when": {"max": 0.5},
        "on_fail": ("High-risk area: run the qa-skeptic agent; for payments, auth or migrations also run "
                    "/second-opinion."),
    },
    "unfinished": {
        "type": "noul",
        "instructions": ("Does the diff add unfinished work: TODO or FIXME notes, debug output, commented-out "
                         "code, placeholder values, or skipped or disabled tests?"),
        "pass_when": {"max": 0.5},
        "on_fail": "Finish or remove leftover TODOs, debug output, placeholders or skipped tests.",
    },
    "unrelated": {
        "type": "noul",
        "instructions": "Does the diff contain changes unrelated to the task goal?",
        "requires_goal": True,
        "pass_when": {"max": 0.5},
        "on_fail": "Split unrelated changes into their own task, or explain them in .ai/memory/state.md.",
    },
    "complete": {
        "type": "noul",
        "instructions": "Does the diff fully implement the task goal, including tests for the new behaviour?",
        "requires_goal": True,
        "pass_when": {"min": 0.5},
        "on_fail": "The change may not fully implement the goal: compare it with the task; add missing parts or tests.",
    },
}

DEFAULT_CONFIG = {
    "mode": "off",
    "private": False,
    "checks": [],
    "check_timeout_seconds": 1800,
    "min_confidence": 0.7,
    "provider": {
        "name": "laya",
        "url": "http://127.0.0.1:8000",
        "path": "/v1/systemone",
        "api_key_env": "DECISION_GATE_API_KEY",
        "model": None,
        "expected_model": None,
        "timeout_seconds": 10,
        "allow_remote_in_private_repo": False,
    },
    "input": {"max_chars": 6000, "on_truncation": "needs_review"},
    "questions": DEFAULT_QUESTIONS,
}

SENSITIVE_FILE = re.compile(
    r"(^|/)(\.env(\.(?!example$|sample$|dist$)[\w.-]+)?|[^/]*\.(pem|key|p12|pfx|jks|keystore)|id_(rsa|dsa|ecdsa|ed25519)[^/]*"
    r"|credentials(\.json)?|secrets?\.(json|ya?ml|toml))$", re.I)
SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED PRIVATE KEY]"),
    (re.compile(r"(?i)\b(api[_-]?key|secret|token|passw(or)?d|private[_-]?key|access[_-]?key|client[_-]?secret)"
                r"(\s*[:=]\s*|\s*=>\s*)(['\"]?)[^\s'\",;]{6,}"), r"\1\2\3[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "[REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"), "[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "[REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "[REDACTED JWT]"),
]


class GateError(Exception):
    """A configuration or environment problem the caller must fix (exit code 2)."""


# --------------------------------------------------------------------------- repository helpers
def git(root, *args, check=True):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, timeout=120)
    if check and r.returncode != 0:
        raise GateError("git %s failed: %s" % (" ".join(args), r.stderr.decode("utf-8", "replace").strip()))
    return r.stdout


def git_text(root, *args, check=True):
    return git(root, *args, check=check).decode("utf-8", "replace").strip()


def find_root(start=None):
    start = start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    r = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"], capture_output=True, timeout=30)
    if r.returncode != 0:
        raise GateError("the decision gate needs a git repository (%s is not inside one)" % start)
    return r.stdout.decode().strip()


def commit_exists(root, ref):
    return subprocess.run(["git", "-C", root, "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
                          capture_output=True, timeout=30).returncode == 0


def has_local_changes(root):
    if not commit_exists(root, "HEAD"):
        return True
    diff = git(root, "diff", "--name-only", "HEAD", "--", ".", *EXCLUDE)
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "--", ".", *EXCLUDE)
    return bool(diff.strip() or untracked.strip())


def resolve_base(root, base_arg=None):
    """The commit the change is measured against."""
    if base_arg:
        if not commit_exists(root, base_arg):
            raise GateError("--base %s is not a commit" % base_arg)
        return git_text(root, "rev-parse", base_arg + "^{commit}")
    if not commit_exists(root, "HEAD"):
        return EMPTY_TREE
    head = git_text(root, "rev-parse", "HEAD")
    if has_local_changes(root):
        return head  # uncommitted work: measure it against HEAD
    candidates = ["@{upstream}", "origin/HEAD", "origin/main", "origin/master", "main", "master"]
    for ref in candidates:
        if commit_exists(root, ref):
            mb = git_text(root, "merge-base", "HEAD", ref, check=False)
            if mb and mb != head:
                return mb
    if commit_exists(root, "HEAD~1"):
        return git_text(root, "rev-parse", "HEAD~1")
    return EMPTY_TREE


def collect_change(root, base):
    """The change from `base` to the working tree (tracked and untracked), excluding .ai/ and .claude/."""
    diff = git(root, "diff", "--no-color", "--no-ext-diff", base, "--", ".", *EXCLUDE)
    numstat = git_text(root, "diff", "--numstat", base, "--", ".", *EXCLUDE)
    files = []
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            files.append({"path": parts[2], "added": parts[0], "deleted": parts[1]})
    untracked = [p for p in git_text(root, "ls-files", "--others", "--exclude-standard", "--", ".", *EXCLUDE)
                 .splitlines() if p]
    h = hashlib.sha256()
    h.update(diff)
    extra_text = []
    for rel in sorted(untracked):
        path = os.path.join(root, rel)
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        h.update(b"\0untracked\0" + rel.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
        n_lines = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
        files.append({"path": rel, "added": str(n_lines), "deleted": "0", "untracked": True})
        if len(data) > MAX_UNTRACKED_BYTES or b"\0" in data[:8000]:
            extra_text.append("diff --git a/%s b/%s\nnew file (%d bytes, not shown)\n" % (rel, rel, len(data)))
        else:
            body = data.decode("utf-8", "replace")
            extra_text.append("diff --git a/%s b/%s\nnew file mode 100644\n--- /dev/null\n+++ b/%s\n%s\n"
                              % (rel, rel, rel, "\n".join("+" + ln for ln in body.splitlines())))
    text = diff.decode("utf-8", "replace") + "".join(extra_text)
    return {"base": base, "diff_text": text, "diff_sha256": h.hexdigest(), "files": files}


def read_goal(root, goal_arg=None):
    if goal_arg:
        return goal_arg.strip()
    path = os.path.join(root, ".ai", "memory", "state.md")
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return ""
    m = re.search(r"\*\*Goal\*\*\s*:\s*(.+)", text)
    goal = m.group(1).strip() if m else ""
    if not goal or goal.startswith("(") or goal.lower() in ("none", "n/a", "-"):
        return ""
    return goal


def task_context(root):
    """The current task's spec (.ai/specs/<T-id>/spec.md), if readiness.py is installed and a spec exists.

    Returns {"task", "goal", "trace"} or None. Never raises: the spec only adds information."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import readiness  # noqa: E402
        task = readiness.current_task(root)
        if not task:
            return None
        path = readiness.spec_path(root, task)
        if not os.path.exists(path):
            return None
        text = readiness.read_file(path)
        return {"task": task, "goal": readiness.spec_goal(text), "trace": readiness.trace(root, task, text)}
    except Exception:
        return None


def is_private_repo(root, cfg):
    if cfg.get("private"):
        return True
    try:
        rel = git_text(root, "rev-parse", "--git-path", "info/exclude")
        path = rel if os.path.isabs(rel) else os.path.join(root, rel)
        with open(path, encoding="utf-8") as fh:
            return any(line.strip() in (".ai/", ".ai") for line in fh)
    except (OSError, GateError):
        return False


def is_local_url(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host in ("localhost", "::1") or host.startswith("127.")


# --------------------------------------------------------------------------- config
def deep_merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if k.startswith("_"):
            continue
        if k == "questions":
            out[k] = {qk: qv for qk, qv in v.items() if not qk.startswith("_")}
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(root):
    path = os.path.join(root, CONFIG_REL)
    user = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                user = json.load(fh)
        except (OSError, ValueError) as exc:
            raise GateError("%s is not valid JSON: %s" % (CONFIG_REL, exc))
    cfg = deep_merge(DEFAULT_CONFIG, user)
    env_mode = os.environ.get("GOD_GATE_MODE", "").strip().lower()
    if env_mode:
        cfg["mode"] = env_mode
    env_url = os.environ.get("GOD_GATE_URL", "").strip()
    if env_url:
        cfg["provider"]["url"] = env_url
    if cfg["mode"] not in MODES:
        raise GateError("mode must be one of %s, got %r" % ("/".join(MODES), cfg["mode"]))
    for qid, q in cfg["questions"].items():
        if q.get("type") not in ("noul", "choice", "score"):
            raise GateError("question %s: type must be noul, choice or score" % qid)
        if not q.get("instructions"):
            raise GateError("question %s: instructions are required" % qid)
        if q["type"] in ("choice", "score") and not q.get("criteria"):
            raise GateError("question %s: %s questions need criteria" % (qid, q["type"]))
    return cfg


def config_digest(cfg):
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- model input
def scrub_secrets(diff_text):
    """Drop sensitive files from the model input and redact secret-looking values. Returns (text, count)."""
    count = 0
    blocks = re.split(r"(?m)^(?=diff --git )", diff_text)
    kept = []
    for block in blocks:
        m = re.match(r"diff --git a/(\S+) b/(\S+)", block)
        if m and (SENSITIVE_FILE.search(m.group(2)) or SENSITIVE_FILE.search(m.group(1))):
            kept.append("diff --git a/%s b/%s\n(sensitive file: contents not sent)\n" % (m.group(1), m.group(2)))
            count += 1
            continue
        kept.append(block)
    text = "".join(kept)
    for rx, repl in SECRET_PATTERNS:
        text, n = rx.subn(repl, text)
        count += n
    return text, count


def build_questions(cfg, has_goal):
    asked = {}
    for qid, q in cfg["questions"].items():
        if q.get("requires_goal") and not has_goal:
            continue
        wire = {"type": q["type"], "instructions": q["instructions"]}
        if q.get("criteria"):
            wire["criteria"] = q["criteria"]
        asked[qid] = wire
    return asked


def build_state(goal, change, max_chars):
    diff_text, redactions = scrub_secrets(change["diff_text"])
    truncated = len(diff_text) > max_chars
    if truncated:
        diff_text = diff_text[:max_chars] + "\n[diff truncated: %d more characters not shown]" % (
            len(diff_text) - max_chars)
    files = "\n".join("%s (+%s -%s)%s" % (f["path"], f["added"], f["deleted"], " new" if f.get("untracked") else "")
                      for f in change["files"]) or "(no files changed)"
    state = {"task_goal": goal or "(not stated)", "changed_files": files, "diff": diff_text}
    return state, {"chars": len(diff_text), "truncated": truncated, "redactions": redactions}


# --------------------------------------------------------------------------- model call
class ModelUnavailable(Exception):
    pass


def _reject_constant(name):
    raise ValueError("non-finite number %s in response" % name)


def call_model(cfg, state, questions):
    prov = cfg["provider"]
    url = prov["url"].rstrip("/") + prov.get("path", "/v1/systemone")
    body = {"state": state, "questions": questions}
    if prov.get("model"):
        body["model"] = prov["model"]
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    key = os.environ.get(prov.get("api_key_env") or "", "")
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=float(prov.get("timeout_seconds", 10))) as resp:
            raw = resp.read(4_000_000)
    except urllib.error.HTTPError as exc:
        detail = exc.read(500).decode("utf-8", "replace") if exc.fp else ""
        raise ModelUnavailable("HTTP %d from %s %s" % (exc.code, url, detail.strip()[:200]))
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ModelUnavailable("cannot reach %s (%s)" % (url, reason))
    latency_ms = round((time.time() - t0) * 1000, 1)
    try:
        data = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except ValueError as exc:
        raise ModelUnavailable("malformed response from %s: %s" % (url, exc))
    if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
        raise ModelUnavailable("response from %s has no answers object" % url)
    missing = [q for q in questions if q not in data["answers"]]
    if missing:
        raise ModelUnavailable("response is missing answers for: %s" % ", ".join(missing))
    return data, latency_ms


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _prob(v, what):
    f = _num(v)
    if f is None or not math.isfinite(f) or f < 0.0 or f > 1.0:
        raise ValueError("%s is not a probability: %r" % (what, v))
    return f


def normalize_answer(qtype, a):
    """Map Jev / laya / vega answer shapes onto one form. Raises ValueError on malformed answers."""
    if not isinstance(a, dict):
        raise ValueError("answer is not an object")
    out = {"abstain": bool(a.get("abstain", False)), "unbound": bool(a.get("unbound", False)),
           "set_size": len(a["prediction_set"]) if isinstance(a.get("prediction_set"), list) else None}
    probs = a.get("probabilities") or a.get("probs") or {}
    if not isinstance(probs, dict):
        probs = {}
    if qtype == "noul":
        p = None
        for key in ("noul", "boolean", "probability", "p_true"):
            if key in a and _num(a[key]) is not None:
                p = _prob(a[key], key)
                break
        if p is None:
            for key in ("true", "True", "yes", "1"):
                if key in probs:
                    p = _prob(probs[key], "probabilities." + key)
                    break
        if p is None:
            raise ValueError("no yes-probability in answer")
        out["value"] = p
        conf = a.get("answer_confidence", a.get("confidence"))
        out["confidence"] = _prob(conf, "confidence") if conf is not None else max(p, 1.0 - p)
    elif qtype == "choice":
        choice = a.get("choice")
        if not isinstance(choice, str) or not choice:
            raise ValueError("no choice in answer")
        out["value"] = choice
        conf = a.get("answer_confidence")
        if conf is None:
            conf = probs.get(choice, a.get("confidence"))
        if conf is None:
            raise ValueError("no confidence for choice")
        out["confidence"] = _prob(conf, "confidence")
    else:
        score = a.get("expected_score", a.get("score"))
        f = _num(score)
        if f is None or not math.isfinite(f):
            raise ValueError("no finite score in answer")
        out["value"] = f
        conf = a.get("answer_confidence", a.get("confidence"))
        if conf is None:
            raise ValueError("no confidence for score")
        out["confidence"] = _prob(conf, "confidence")
    for v in probs.values():
        f = _num(v)
        if f is not None and not math.isfinite(f):
            raise ValueError("non-finite probability")
    return out


def rule_passes(qtype, rule, value):
    rule = rule or {}
    if qtype == "choice":
        allowed = rule.get("in")
        return True if allowed is None else value in allowed
    lo, hi = rule.get("min"), rule.get("max")
    if lo is not None and value < float(lo):
        return False
    if hi is not None and value > float(hi):
        return False
    return True


def describe(qtype, norm):
    if qtype == "noul":
        return "yes %.2f" % norm["value"]
    if qtype == "choice":
        return "%s" % norm["value"]
    return "score %.2f" % norm["value"]


def judge(cfg, asked, data):
    """Turn model answers into per-question results, reasons and advice."""
    results, reasons, advice = {}, [], []
    for qid in asked:
        q = cfg["questions"][qid]
        raw = data["answers"][qid]
        try:
            norm = normalize_answer(q["type"], raw)
        except ValueError as exc:
            raise ModelUnavailable("answer for %s is malformed: %s" % (qid, exc))
        min_conf = float(q.get("min_confidence", cfg.get("min_confidence", 0.7)))
        unsure = []
        if norm["abstain"]:
            unsure.append("model abstained")
        if norm["unbound"]:
            unsure.append("input is outside what the model knows")
        if norm["set_size"] is not None and norm["set_size"] > 1:
            unsure.append("%d answers are plausible" % norm["set_size"])
        if norm["confidence"] < min_conf:
            unsure.append("confidence %.2f < %.2f" % (norm["confidence"], min_conf))
        passed = rule_passes(q["type"], q.get("pass_when"), norm["value"])
        status = "unsure" if unsure else ("pass" if passed else "fail")
        results[qid] = {"status": status, "summary": describe(q["type"], norm), "normalized": norm, "raw": raw}
        if unsure:
            reasons.append("%s: model is unsure (%s)" % (qid, "; ".join(unsure)))
            advice.append("Model unsure on %s: review it yourself or run the qa-skeptic agent." % qid)
        elif not passed:
            reasons.append("%s: %s fails %s" % (qid, describe(q["type"], norm), json.dumps(q.get("pass_when"))))
            if q.get("on_fail"):
                advice.append(q["on_fail"])
    return results, reasons, advice


# --------------------------------------------------------------------------- checks
def run_checks(root, cfg):
    out = []
    for cmd in cfg.get("checks") or []:
        t0 = time.time()
        try:
            r = subprocess.run(cmd, shell=True, cwd=root, capture_output=True,
                               timeout=float(cfg.get("check_timeout_seconds", 1800)))
            code, output = r.returncode, (r.stdout + r.stderr)
        except subprocess.TimeoutExpired as exc:
            code, output = -1, ((exc.stdout or b"") + (exc.stderr or b"") + b"\n[timed out]")
        text = output.decode("utf-8", "replace")
        out.append({"cmd": cmd, "exit": code, "seconds": round(time.time() - t0, 1),
                    "output_sha256": hashlib.sha256(output).hexdigest(), "output_tail": text[-1500:]})
        if code != 0:
            break  # fail fast: later checks would not change the verdict
    return out


# --------------------------------------------------------------------------- receipts
def receipts_dir(root):
    return os.path.join(root, RECEIPTS_REL)


def write_receipt(root, receipt):
    d = receipts_dir(root)
    os.makedirs(d, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    name = "%s-%s.json" % (stamp, receipt["verdict"])
    text = json.dumps(receipt, indent=2, sort_keys=True)
    with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
        fh.write(text)
    tmp = os.path.join(d, "latest.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, os.path.join(d, "latest.json"))
    old = sorted(f for f in os.listdir(d) if f.endswith(".json") and f != "latest.json")
    for f in old[:-KEEP_RECEIPTS]:
        try:
            os.remove(os.path.join(d, f))
        except OSError:
            pass
    return os.path.join(RECEIPTS_REL, name)


def load_latest(root):
    path = os.path.join(receipts_dir(root), "latest.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def verify_receipt(root, receipt, cfg=None):
    """Is the receipt still bound to the current code and config? Returns a list of problems."""
    if receipt is None:
        return ["no receipt yet"]
    problems = []
    b = receipt.get("binding", {})
    base = b.get("base")
    if not base or (base != EMPTY_TREE and not commit_exists(root, base)):
        return ["base commit %s no longer exists" % (base or "?")]
    if base != EMPTY_TREE and commit_exists(root, "HEAD") and subprocess.run(
            ["git", "-C", root, "merge-base", "--is-ancestor", base, "HEAD"], capture_output=True).returncode != 0:
        problems.append("base %s is no longer an ancestor of HEAD" % base[:12])
    change = collect_change(root, base)
    if change["diff_sha256"] != b.get("diff_sha256"):
        problems.append("code changed since the receipt (diff differs)")
    cfg = cfg if cfg is not None else load_config(root)
    if config_digest(cfg) != b.get("config_sha256"):
        problems.append("decision-gate config changed since the receipt")
    if receipt.get("gate_version") != GATE_VERSION:
        problems.append("receipt was written by a different gate version")
    return problems


def publication_check(root):
    """For hooks: may the agent publish (push / open a PR)? Returns (allowed, reason)."""
    cfg = load_config(root)
    if cfg["mode"] != "required":
        return True, ""
    receipt = load_latest(root)
    if receipt is None:
        return False, "decision gate is in required mode and has no receipt: run /ready-gate first"
    if receipt.get("verdict") != READY:
        return False, "latest decision-gate verdict is %s: %s" % (
            receipt.get("verdict"), "; ".join(receipt.get("reasons", [])[:3]))
    problems = verify_receipt(root, receipt, cfg)
    if problems:
        return False, "decision-gate receipt is stale (%s): run /ready-gate again" % "; ".join(problems)
    return True, ""


# --------------------------------------------------------------------------- commands
def gate_check(root, goal_arg=None, base_arg=None, skip_checks=False):
    cfg = load_config(root)
    if cfg["mode"] == "off":
        return {"verdict": OFF, "mode": "off", "reasons": ["decision gate is off (.ai/decision-gate.json)"],
                "advice": []}, None
    base = resolve_base(root, base_arg)
    change = collect_change(root, base)
    goal = read_goal(root, goal_arg)
    task = None if goal_arg else task_context(root)
    if task and task["goal"]:
        goal = task["goal"]  # the spec's title, why, requirements and acceptance criteria beat a one-line goal
    prov = cfg["provider"]
    receipt = {
        "gate_version": GATE_VERSION,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "mode": cfg["mode"],
        "verdict": None, "reasons": [], "advice": [],
        "binding": {
            "base": base,
            "head": git_text(root, "rev-parse", "HEAD") if commit_exists(root, "HEAD") else None,
            "diff_sha256": change["diff_sha256"],
            "config_sha256": config_digest(cfg),
            "goal_sha256": hashlib.sha256(goal.encode("utf-8")).hexdigest(),
        },
        "files": change["files"],
        "checks": [], "checks_skipped": bool(skip_checks),
        "model": {"provider": prov.get("name"), "endpoint_host": urllib.parse.urlparse(prov["url"]).netloc,
                  "requested_model": prov.get("model"), "expected_model": prov.get("expected_model"),
                  "reported_model": None, "latency_ms": None},
        "input": None, "answers": {},
    }
    caps = []  # reasons that stop "ready" without being failures of the change itself
    if task:
        t = task["trace"]
        receipt["task"] = {"id": task["task"], "criteria": t["criteria"],
                           "uncovered": [c["id"] for c in t["uncovered"]], "converged": t["converged"],
                           "open_tasks": t["open_tasks"]}
        if t["uncovered"]:
            ids = ", ".join(c["id"] for c in t["uncovered"])
            caps.append("acceptance criteria with no test naming them: %s" % ids)
            receipt["advice"].append("Add a test for each of %s and name it after the criterion "
                                     "(e.g. test_ac_002_...), or explain the gap in the spec." % ids)
        if not t["converged"]:
            receipt["advice"].append("Run /converge %s to compare the code with its spec before review." % task["task"])

    def finish(verdict, reasons=(), advice=()):
        receipt["verdict"] = verdict
        receipt["reasons"] = list(dict.fromkeys(list(receipt["reasons"]) + list(reasons)))
        receipt["advice"] = list(dict.fromkeys(list(receipt["advice"]) + list(advice)))
        return receipt, write_receipt(root, receipt)

    if not change["files"]:
        return finish(NOT_READY, ["no changes found against base %s" % base[:12]],
                      ["Nothing to check: make the change first, or pass --base."])

    # 1. deterministic checks first
    if skip_checks:
        caps.append("checks were skipped (--skip-checks)")
    elif not cfg.get("checks"):
        caps.append("no deterministic checks are configured in .ai/decision-gate.json")
    else:
        receipt["checks"] = run_checks(root, cfg)
        failed = [c for c in receipt["checks"] if c["exit"] != 0]
        if failed:
            c = failed[0]
            return finish(NOT_READY, ["check failed: %s (exit %s)" % (c["cmd"], c["exit"])],
                          ["Fix the failing check; the model is only asked after every check passes."])

    # privacy: never send private code to a remote model
    if not is_local_url(prov["url"]) and is_private_repo(root, cfg) and not prov.get("allow_remote_in_private_repo"):
        return finish(UNAVAILABLE, ["refused: %s is remote and this repo is private" % receipt["model"]["endpoint_host"]],
                      ["Use a local model server (laya-serve or vega_server.py on 127.0.0.1) for private repos."])

    asked = build_questions(cfg, bool(goal))
    if not goal and any(q.get("requires_goal") for q in cfg["questions"].values()):
        caps.append("no task goal (set Goal in .ai/memory/state.md or pass --goal), so goal questions were skipped")
    if not asked:
        return finish(UNAVAILABLE, caps + ["no questions to ask"], [])
    state, meta = build_state(goal, change, int(cfg["input"].get("max_chars", 6000)))
    receipt["input"] = dict(meta, sha256=hashlib.sha256(
        json.dumps({"state": state, "questions": asked}, sort_keys=True).encode("utf-8")).hexdigest())

    # 2. ask the model
    try:
        data, latency = call_model(cfg, state, asked)
        receipt["model"]["latency_ms"] = latency
        receipt["model"]["reported_model"] = data.get("model")
        expected = prov.get("expected_model")
        if expected and data.get("model") != expected:
            raise ModelUnavailable("server answered as model %r, expected %r" % (data.get("model"), expected))
        results, reasons, advice = judge(cfg, asked, data)
    except ModelUnavailable as exc:
        return finish(UNAVAILABLE, caps + [str(exc)],
                      ["Start the model server (see README: decision gate), or set mode to off/advisory."])
    receipt["answers"] = results

    # re-check after inference: a check (formatter, codegen) or a person may have changed files meanwhile
    if collect_change(root, base)["diff_sha256"] != change["diff_sha256"]:
        caps.append("files changed while the gate was running (a check may rewrite code); run it again")
    if config_digest(load_config(root)) != receipt["binding"]["config_sha256"]:
        caps.append("decision-gate config changed while the gate was running; run it again")
    if meta["truncated"] and cfg["input"].get("on_truncation", "needs_review") != "allow":
        caps.append("the diff was too long for the model (%d chars shown); split the change or review it yourself"
                    % meta["chars"])
    if reasons:
        return finish(NEEDS_REVIEW, reasons + caps, advice)
    if caps:
        return finish(NEEDS_REVIEW, caps, ["Address the notes above to get a 'ready' verdict."])
    return finish(READY)


def print_check(receipt, path):
    v = receipt["verdict"]
    if v == OFF:
        print("Decision gate: OFF (set \"mode\" in .ai/decision-gate.json to advisory or required)")
        return
    m = receipt.get("model") or {}
    lat = " %s ms" % m["latency_ms"] if m.get("latency_ms") is not None else ""
    print("Decision gate: %s  (mode: %s, model: %s @ %s%s)" % (
        v.upper(), receipt["mode"], m.get("reported_model") or m.get("provider"), m.get("endpoint_host"), lat))
    checks = receipt.get("checks") or []
    if receipt.get("checks_skipped"):
        print("Checks: skipped")
    elif checks:
        ok = sum(1 for c in checks if c["exit"] == 0)
        print("Checks: %d/%d passed" % (ok, len(checks)))
    if receipt.get("answers"):
        print("Questions:")
        for qid, r in receipt["answers"].items():
            n = r["normalized"]
            print("  %-12s %-22s conf %.2f  %s" % (qid, r["summary"], n["confidence"], r["status"].upper()))
    inp = receipt.get("input") or {}
    if inp.get("redactions"):
        print("Input: %d secret-looking value(s) or sensitive file(s) withheld from the model" % inp["redactions"])
    if receipt.get("reasons"):
        print("Reasons:")
        for r in receipt["reasons"]:
            print("  - " + r)
    if receipt.get("advice"):
        print("Next:")
        for a in receipt["advice"]:
            print("  - " + a)
    if path:
        print("Receipt: " + path.replace(os.sep, "/"))


def cmd_check(args):
    root = find_root()
    receipt, path = gate_check(root, args.goal, args.base, args.skip_checks)
    if args.json:
        print(json.dumps(dict(receipt, receipt_path=path), indent=2, sort_keys=True))
    else:
        print_check(receipt, path)
    if receipt["mode"] == "required" and receipt["verdict"] != READY:
        return 1
    return 0


def cmd_verify(args):
    root = find_root()
    receipt = load_latest(root)
    problems = verify_receipt(root, receipt)
    fresh = not problems
    if args.json:
        print(json.dumps({"fresh": fresh, "verdict": (receipt or {}).get("verdict"), "problems": problems}, indent=2))
    elif receipt is None:
        print("No decision-gate receipt yet: run decision_gate.py check")
    else:
        print("Latest receipt: %s, %s (%s)" % ((receipt.get("verdict") or "?").upper(),
                                             "fresh" if fresh else "STALE", receipt.get("created_at")))
        for p in problems:
            print("  - " + p)
    return 0 if fresh and receipt and receipt.get("verdict") == READY else 1


def cmd_status(args):
    root = find_root()
    cfg = load_config(root)
    prov = cfg["provider"]
    private = is_private_repo(root, cfg)
    local = is_local_url(prov["url"])
    print("Mode: %s" % cfg["mode"])
    print("Provider: %s at %s%s" % (prov.get("name"), prov["url"], prov.get("path", "")))
    print("Repo: %s; endpoint is %s%s" % ("private" if private else "shared", "local" if local else "REMOTE",
                                         " -> refused for this repo" if private and not local and
                                         not prov.get("allow_remote_in_private_repo") else ""))
    key_env = prov.get("api_key_env")
    print("API key: %s" % ("set in $%s" % key_env if key_env and os.environ.get(key_env) else "not set"))
    print("Checks: %s" % (", ".join(cfg["checks"]) if cfg["checks"] else "none configured"))
    try:
        urllib.request.urlopen(urllib.request.Request(prov["url"], method="GET"), timeout=3)
        print("Server: reachable")
    except urllib.error.HTTPError:
        print("Server: reachable")
    except Exception as exc:
        print("Server: NOT reachable (%s)" % getattr(exc, "reason", exc))
    receipt = load_latest(root)
    if receipt:
        problems = verify_receipt(root, receipt, cfg)
        print("Latest receipt: %s, %s" % (receipt.get("verdict"), "fresh" if not problems else "stale: " + "; ".join(problems)))
    else:
        print("Latest receipt: none")
    return 0


def cmd_calibrate(args):
    """Measure the model on labelled diffs. Each JSONL line:
    {"diff": "...", "goal": "...", "labels": {"high_risk": true, "unfinished": false, ...}}"""
    root = find_root()
    cfg = load_config(root)
    prov = cfg["provider"]
    if not is_local_url(prov["url"]) and is_private_repo(root, cfg) and not prov.get("allow_remote_in_private_repo"):
        raise GateError("refused: remote model and private repo (see `status`)")
    stats = {}
    with open(args.data, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    for i, row in enumerate(rows, 1):
        labels = row.get("labels") or {}
        goal = row.get("goal", "")
        change = {"diff_text": row["diff"], "files": row.get("files") or []}
        asked = {k: v for k, v in build_questions(cfg, bool(goal)).items() if k in labels}
        if not asked:
            continue
        state, _ = build_state(goal, change, int(cfg["input"].get("max_chars", 6000)))
        try:
            data, _ = call_model(cfg, state, asked)
        except ModelUnavailable as exc:
            raise GateError("row %d: %s" % (i, exc))
        for qid in asked:
            q = cfg["questions"][qid]
            try:
                norm = normalize_answer(q["type"], data["answers"][qid])
            except ValueError as exc:
                raise GateError("row %d, %s: malformed answer: %s" % (i, qid, exc))
            truth = labels[qid]
            s = stats.setdefault(qid, {"n": 0, "correct": 0, "brier": 0.0, "unsure": 0, "false_pass": 0,
                                       "should_fail": 0, "bins": [[0, 0, 0.0] for _ in range(10)]})
            s["n"] += 1
            if q["type"] == "noul":
                t = 1.0 if truth in (True, "true", "yes", 1) else 0.0
                correct = (norm["value"] >= 0.5) == (t == 1.0)
                s["brier"] += (norm["value"] - t) ** 2
                truth_value = t
            elif q["type"] == "choice":
                correct = norm["value"] == truth
                truth_value = truth
            else:
                correct = abs(norm["value"] - float(truth)) < 0.5
                truth_value = float(truth)
            s["correct"] += int(correct)
            min_conf = float(q.get("min_confidence", cfg.get("min_confidence", 0.7)))
            unsure = norm["confidence"] < min_conf or norm["abstain"] or (norm["set_size"] or 0) > 1
            s["unsure"] += int(unsure)
            truth_pass = rule_passes(q["type"], q.get("pass_when"), truth_value)
            if not truth_pass:
                s["should_fail"] += 1
                if not unsure and rule_passes(q["type"], q.get("pass_when"), norm["value"]):
                    s["false_pass"] += 1
            b = min(int(norm["confidence"] * 10), 9)
            s["bins"][b][0] += 1
            s["bins"][b][1] += int(correct)
            s["bins"][b][2] += norm["confidence"]
    if not stats:
        print("No labelled questions matched the configured questions.")
        return 1
    print("%-12s %5s %9s %7s %6s %8s  %s" % ("question", "n", "accuracy", "brier", "ece", "unsure", "missed failures"))
    for qid, s in stats.items():
        n = s["n"]
        ece = sum(abs(b[1] - b[2]) for b in s["bins"] if b[0]) / n
        brier = "%.3f" % (s["brier"] / n) if cfg["questions"][qid]["type"] == "noul" else "-"
        missed = "%d of %d" % (s["false_pass"], s["should_fail"]) if s["should_fail"] else "-"
        print("%-12s %5d %9.3f %7s %6.3f %7.0f%%  %s" % (qid, n, s["correct"] / n, brier, ece, 100.0 * s["unsure"] / n, missed))
    print("\n'missed failures' = labelled problems the gate would have passed confidently. Aim for 0 before "
          "using required mode; raise min_confidence or tighten pass_when if not.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="decision_gate.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("check", help="run checks, then ask the model; write a receipt")
    c.add_argument("--goal", help="task goal (default: Goal line of .ai/memory/state.md)")
    c.add_argument("--base", help="commit to compare against (default: HEAD if there is uncommitted work)")
    c.add_argument("--skip-checks", action="store_true", help="ask the model without running checks (never 'ready')")
    c.add_argument("--json", action="store_true")
    v = sub.add_parser("verify", help="is the latest receipt still fresh?")
    v.add_argument("--json", action="store_true")
    sub.add_parser("status", help="configuration, server reachability, latest receipt")
    k = sub.add_parser("calibrate", help="measure the model on labelled diffs (JSONL)")
    k.add_argument("--data", required=True)
    args = ap.parse_args(argv)
    handlers = {"check": cmd_check, "verify": cmd_verify, "status": cmd_status, "calibrate": cmd_calibrate}
    if args.cmd not in handlers:
        ap.print_help()
        return 2
    try:
        return handlers[args.cmd](args)
    except GateError as exc:
        print("decision gate error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
