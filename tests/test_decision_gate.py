"""Tests for the decision gate, its publication guard and the vega wrapper's wire translation.

Runs against a fake /v1/systemone server and a real git repo with the kit installed. No model,
GPU or network needed:  python3 -m unittest -v tests/test_decision_gate.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(".claude", "god", "decide", "decision_gate.py")
GUARD = os.path.join(".claude", "god", "hooks", "pretool_guard.sh")

GOOD = {
    "high_risk": {"type": "noul", "noul": 0.08, "confidence": 0.92, "answer_confidence": 0.92},
    "unfinished": {"type": "noul", "noul": 0.05, "confidence": 0.95, "answer_confidence": 0.95},
    "unrelated": {"type": "noul", "noul": 0.10, "confidence": 0.90, "answer_confidence": 0.90},
    "complete": {"type": "noul", "noul": 0.91, "confidence": 0.91, "answer_confidence": 0.91},
}


class FakeServer:
    """A /v1/systemone server whose behaviour each test sets."""

    def __init__(self):
        self.requests = []
        self.behavior = {"answers": GOOD, "model": "fake-1.0"}
        fake = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append({"body": body, "auth": self.headers.get("Authorization")})
                b = fake.behavior
                if b.get("sleep"):
                    time.sleep(b["sleep"])
                if b.get("status"):
                    self.send_response(b["status"])
                    self.end_headers()
                    self.wfile.write(b'{"error":"boom"}')
                    return
                raw = b.get("raw")
                if raw is None:
                    answers = {q: b["answers"][q] for q in body["questions"] if q in b["answers"]}
                    raw = json.dumps({"model": b.get("model"), "answers": answers,
                                      "usage": {"input_tokens": 10, "output_tokens": 0}}).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the gate already gave up (timeout test)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


def sh(cwd, *cmd, check=True, env=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise AssertionError("%s failed: %s %s" % (cmd, r.stdout, r.stderr))
    return r


class GateTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = FakeServer()

    @classmethod
    def tearDownClass(cls):
        cls.server.close()

    def setUp(self):
        self.server.requests.clear()
        self.server.behavior = {"answers": GOOD, "model": "fake-1.0"}
        self.repo = tempfile.mkdtemp(prefix="gate-")
        sh(self.repo, "git", "init", "-q", "-b", "main")
        sh(self.repo, "git", "config", "user.email", "t@t")
        sh(self.repo, "git", "config", "user.name", "t")
        with open(os.path.join(self.repo, "app.py"), "w") as fh:
            fh.write("def total(xs):\n    return sum(xs)\n")
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-qm", "base")
        sh(self.repo, "bash", os.path.join(KIT, "install.sh"), self.repo, *self.install_args())
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-qm", "kit", "--allow-empty")  # private mode commits nothing
        self.set_goal("Make total() ignore None values")
        self.configure(mode="advisory", checks=["python3 -c \"print('tests ok')\""])
        self.change_code()

    def install_args(self):
        return []

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    # helpers -----------------------------------------------------------------
    def configure(self, **kw):
        path = os.path.join(self.repo, ".ai", "decision-gate.json")
        with open(path) as fh:
            cfg = json.load(fh)
        provider = kw.pop("provider", {})
        cfg["provider"]["url"] = "http://127.0.0.1:%d" % self.server.port
        cfg["provider"]["timeout_seconds"] = 2
        cfg["provider"].update(provider)
        cfg.update(kw)
        with open(path, "w") as fh:
            json.dump(cfg, fh, indent=2)

    def set_goal(self, goal):
        path = os.path.join(self.repo, ".ai", "memory", "state.md")
        with open(path) as fh:
            text = fh.read()
        import re
        with open(path, "w") as fh:
            fh.write(re.sub(r"\*\*Goal\*\*:.*", "**Goal**: " + goal, text))

    def change_code(self, extra=""):
        with open(os.path.join(self.repo, "app.py"), "w") as fh:
            fh.write("def total(xs):\n    return sum(x for x in xs if x is not None)\n" + extra)

    def env(self, **kw):
        e = dict(os.environ, CLAUDE_PROJECT_DIR=self.repo)
        e.pop("GOD_GATE_MODE", None)
        e.update(kw)
        return e

    def check(self, *args, **envkw):
        r = sh(self.repo, sys.executable, GATE, "check", "--json", *args, check=False, env=self.env(**envkw))
        try:
            data = json.loads(r.stdout)
        except ValueError:
            raise AssertionError("not JSON (exit %d): %s %s" % (r.returncode, r.stdout, r.stderr))
        return r.returncode, data

    def guard(self, command):
        payload = json.dumps({"tool_name": "Bash", "cwd": self.repo, "tool_input": {"command": command}})
        r = subprocess.run(["bash", GUARD], cwd=self.repo, input=payload, capture_output=True, text=True,
                           env=self.env())
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None


class TestVerdicts(GateTestBase):
    def test_ready_path_writes_bound_receipt(self):
        code, r = self.check()
        self.assertEqual(r["verdict"], "ready", r["reasons"])
        self.assertEqual(code, 0)
        self.assertEqual(r["model"]["reported_model"], "fake-1.0")
        self.assertEqual(r["checks"][0]["exit"], 0)
        self.assertTrue(os.path.exists(os.path.join(self.repo, r["receipt_path"])))
        self.assertTrue(os.path.exists(os.path.join(self.repo, ".ai/review/receipts/latest.json")))
        self.assertEqual(len(self.server.requests), 1)
        body = self.server.requests[0]["body"]
        self.assertEqual(set(body["questions"]), set(GOOD))
        self.assertIn("is not None", body["state"]["diff"])
        self.assertEqual(body["state"]["task_goal"], "Make total() ignore None values")

    def test_off_mode_does_nothing(self):
        self.configure(mode="off")
        code, r = self.check()
        self.assertEqual((code, r["verdict"]), (0, "off"))
        self.assertEqual(self.server.requests, [])
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".ai/review/receipts")))

    def test_failed_check_means_model_never_asked(self):
        self.configure(checks=["python3 -c \"import sys; sys.exit(3)\"", "echo never-runs"])
        code, r = self.check()
        self.assertEqual(r["verdict"], "not_ready")
        self.assertEqual(self.server.requests, [])
        self.assertEqual(len(r["checks"]), 1)  # fail fast
        self.assertIn("exit 3", r["reasons"][0])

    def test_no_checks_configured_caps_at_needs_review(self):
        self.configure(checks=[])
        _, r = self.check()
        self.assertEqual(r["verdict"], "needs_review")
        self.assertTrue(any("no deterministic checks" in x for x in r["reasons"]))

    def test_skip_checks_never_ready(self):
        _, r = self.check("--skip-checks")
        self.assertEqual(r["verdict"], "needs_review")

    def test_high_risk_gives_advice(self):
        self.server.behavior["answers"] = dict(GOOD, high_risk={"noul": 0.88, "answer_confidence": 0.88})
        _, r = self.check()
        self.assertEqual(r["verdict"], "needs_review")
        self.assertTrue(any("qa-skeptic" in a for a in r["advice"]))

    def test_unsure_answers_are_not_ready(self):
        cases = {
            "low confidence": {"noul": 0.45, "answer_confidence": 0.55},
            "abstain": {"noul": 0.05, "confidence": 0.95, "abstain": True},
            "wide set": {"noul": 0.1, "confidence": 0.9, "prediction_set": ["false", "true"]},
            "unbound": {"noul": 0.1, "confidence": 0.9, "unbound": True},
        }
        for name, ans in cases.items():
            with self.subTest(name):
                self.server.behavior["answers"] = dict(GOOD, unfinished=ans)
                _, r = self.check()
                self.assertEqual(r["verdict"], "needs_review")
                self.assertEqual(r["answers"]["unfinished"]["status"], "unsure")

    def test_vega_and_jev_answer_shapes_are_understood(self):
        vega_like = {q: {"boolean": a["noul"], "confidence": a["confidence"], "abstain": False,
                         "prediction_set": ["true" if a["noul"] > .5 else "false"]} for q, a in GOOD.items()}
        jev_like = {q: {"type": "noul", "noul": a["noul"], "confidence": a["confidence"]} for q, a in GOOD.items()}
        for name, answers in (("vega", vega_like), ("jev", jev_like)):
            with self.subTest(name):
                self.server.behavior["answers"] = answers
                _, r = self.check()
                self.assertEqual(r["verdict"], "ready", r["reasons"])

    def test_broken_model_responses_are_unavailable(self):
        cases = {
            "http 500": {"status": 500},
            "malformed json": {"raw": b"<html>oops"},
            "nan": {"raw": b'{"answers": {"high_risk": {"noul": NaN}}}'},
            "missing answers": {"answers": {"high_risk": GOOD["high_risk"]}},
            "probability > 1": {"answers": dict(GOOD, complete={"noul": 1.7, "confidence": 0.9})},
        }
        for name, behavior in cases.items():
            with self.subTest(name):
                self.server.behavior = dict({"answers": GOOD, "model": "fake-1.0"}, **behavior)
                code, r = self.check()
                self.assertEqual(r["verdict"], "unavailable")
                self.assertEqual(code, 0)  # advisory never blocks

    def test_timeout_advisory_vs_required(self):
        self.server.behavior["sleep"] = 3
        code, r = self.check()
        self.assertEqual((code, r["verdict"]), (0, "unavailable"))
        self.configure(mode="required")
        code, r = self.check()
        self.assertEqual((code, r["verdict"]), (1, "unavailable"))

    def test_server_down(self):
        self.configure(provider={"url": "http://127.0.0.1:9"})
        code, r = self.check()
        self.assertEqual(r["verdict"], "unavailable")
        self.assertIn("cannot reach", r["reasons"][-1])

    def test_unexpected_model_is_refused(self):
        self.configure(provider={"expected_model": "jev-1.13.0"})
        _, r = self.check()
        self.assertEqual(r["verdict"], "unavailable")
        self.assertIn("expected 'jev-1.13.0'", " ".join(r["reasons"]))

    def test_truncated_input_needs_review(self):
        self.configure(input={"max_chars": 40, "on_truncation": "needs_review"})
        _, r = self.check()
        self.assertEqual(r["verdict"], "needs_review")
        self.assertTrue(r["input"]["truncated"])

    def test_no_goal_skips_goal_questions(self):
        self.set_goal("(none yet — run /onboard-repo or /start-task)")
        _, r = self.check()
        self.assertEqual(set(self.server.requests[0]["body"]["questions"]), {"high_risk", "unfinished"})
        self.assertEqual(r["verdict"], "needs_review")
        _, r = self.check("--goal", "ignore None values")
        self.assertEqual(r["verdict"], "ready")

    def test_secrets_and_sensitive_files_withheld(self):
        self.change_code('API_KEY = "sk-abcdefghijklmnopqrstuvwxyz123456"\npassword = "hunter2hunter2"\n')
        with open(os.path.join(self.repo, ".env.production"), "w") as fh:
            fh.write("DB_PASSWORD=supersecretvalue\n")
        _, r = self.check()
        sent = json.dumps(self.server.requests[0]["body"])
        for secret in ("sk-abcdefghijklmnopqrstuvwxyz123456", "hunter2hunter2", "supersecretvalue"):
            self.assertNotIn(secret, sent)
        self.assertIn("sensitive file", sent)
        self.assertGreaterEqual(r["input"]["redactions"], 3)

    def test_api_key_sent_from_env(self):
        self.check(DECISION_GATE_API_KEY="k-123")
        self.assertEqual(self.server.requests[0]["auth"], "Bearer k-123")

    def test_env_mode_override(self):
        code, r = self.check(GOD_GATE_MODE="off")
        self.assertEqual(r["verdict"], "off")

    def test_no_changes(self):
        sh(self.repo, "git", "checkout", "-q", "--", "app.py")
        _, r = self.check("--base", "HEAD")
        self.assertEqual(r["verdict"], "not_ready")
        self.assertEqual(self.server.requests, [])

    def test_check_that_rewrites_code_is_caught(self):
        self.configure(checks=["python3 -c \"open('app.py','a').write('# formatted\\n')\""])
        _, r = self.check()
        self.assertEqual(r["verdict"], "needs_review")
        self.assertTrue(any("files changed while the gate was running" in x for x in r["reasons"]))


class TestReceipts(GateTestBase):
    def verify(self):
        r = sh(self.repo, sys.executable, GATE, "verify", "--json", check=False, env=self.env())
        return r.returncode, json.loads(r.stdout)

    def test_fresh_then_stale_on_code_change(self):
        self.check()
        code, v = self.verify()
        self.assertTrue(v["fresh"], v)
        self.assertEqual(code, 0)
        self.change_code("# one more line\n")
        code, v = self.verify()
        self.assertFalse(v["fresh"])
        self.assertEqual(code, 1)

    def test_brain_updates_do_not_stale_the_receipt(self):
        self.check()
        with open(os.path.join(self.repo, ".ai", "tasks.md"), "a") as fh:
            fh.write("- [x] T-001 done\n")
        self.assertTrue(self.verify()[1]["fresh"])

    def test_commit_keeps_receipt_fresh_when_content_is_unchanged(self):
        self.check()
        sh(self.repo, "git", "commit", "-qam", "fix total")
        self.assertTrue(self.verify()[1]["fresh"], self.verify()[1])

    def test_config_change_stales_receipt(self):
        self.check()
        self.configure(min_confidence=0.6)
        _, v = self.verify()
        self.assertFalse(v["fresh"])
        self.assertTrue(any("config changed" in p for p in v["problems"]))

    def test_untracked_new_file_is_bound(self):
        with open(os.path.join(self.repo, "new_module.py"), "w") as fh:
            fh.write("X = 1\n")
        self.check()
        with open(os.path.join(self.repo, "new_module.py"), "w") as fh:
            fh.write("X = 2\n")
        self.assertFalse(self.verify()[1]["fresh"])


class TestPublicationGuard(GateTestBase):
    def test_advisory_never_blocks_push(self):
        self.assertIsNone(self.guard("git push origin main"))

    def test_required_mode(self):
        self.configure(mode="required")
        d = self.guard("git push origin main")
        self.assertEqual(d["permissionDecision"], "deny")
        self.assertIn("no receipt", d["permissionDecisionReason"])
        self.assertEqual(self.check()[1]["verdict"], "ready")
        self.assertIsNone(self.guard("git push origin main"))
        self.assertIsNone(self.guard("gh pr create --fill"))
        self.change_code("# edited after the gate\n")
        d = self.guard("npm test && git -C . push")
        self.assertEqual(d["permissionDecision"], "deny")
        self.assertIn("stale", d["permissionDecisionReason"])
        self.assertIsNone(self.guard("git status"))

    def test_required_mode_blocks_needs_review(self):
        self.configure(mode="required")
        self.server.behavior["answers"] = dict(GOOD, high_risk={"noul": 0.9, "answer_confidence": 0.9})
        self.assertEqual(self.check()[1]["verdict"], "needs_review")
        self.assertEqual(self.guard("gh pr create")["permissionDecision"], "deny")

    def test_editing_gate_config_asks(self):
        payload = json.dumps({"tool_name": "Edit", "cwd": self.repo,
                              "tool_input": {"file_path": os.path.join(self.repo, ".ai", "decision-gate.json")}})
        r = subprocess.run(["bash", GUARD], cwd=self.repo, input=payload, capture_output=True, text=True,
                           env=self.env())
        self.assertEqual(json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"], "ask")
        self.assertEqual(self.guard("sed -i s/advisory/off/ .ai/decision-gate.json")["permissionDecision"], "ask")


class TestPrivateRepo(GateTestBase):
    def install_args(self):
        return ["--private"]

    def test_remote_model_refused_without_sending_anything(self):
        self.configure(provider={"url": "http://localhost.example.com:%d" % self.server.port})
        _, r = self.check()
        self.assertEqual(r["verdict"], "unavailable")
        self.assertIn("private", r["reasons"][-1])
        self.assertEqual(self.server.requests, [])

    def test_local_model_allowed(self):
        _, r = self.check()
        self.assertEqual(r["verdict"], "ready", r["reasons"])

    def test_installer_marked_config_private(self):
        with open(os.path.join(self.repo, ".ai", "decision-gate.json")) as fh:
            self.assertTrue(json.load(fh)["private"])


class TestCalibrate(GateTestBase):
    def test_reports_metrics_and_missed_failures(self):
        rows = [
            {"goal": "x", "diff": "+ pay(amount * 1.1)", "labels": {"high_risk": True}},
            {"goal": "x", "diff": "+ print('debug')", "labels": {"high_risk": False, "unfinished": True}},
            {"goal": "x", "diff": "+ return a + b", "labels": {"high_risk": False, "unfinished": False}},
        ]
        data = os.path.join(self.repo, "labelled.jsonl")
        with open(data, "w") as fh:
            fh.write("\n".join(json.dumps(r) for r in rows))
        r = sh(self.repo, sys.executable, GATE, "calibrate", "--data", data, env=self.env())
        self.assertIn("high_risk", r.stdout)
        # GOOD says "not risky" (0.08) for the payment diff: one confident miss of a real failure
        self.assertRegex(r.stdout, r"high_risk\s+3\s+0\.667.*1 of 1")
        self.assertRegex(r.stdout, r"unfinished\s+2\s+0\.500.*1 of 1")


class TestVegaWrapper(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "vega_server", os.path.join(KIT, "template", ".claude", "god", "decide", "vega_server.py"))
        cls.vs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.vs)

    def test_translation_round_trip(self):
        class StubEngine:
            def decide(self, state, questions, mode):
                assert mode == "engine"
                assert questions["risky"]["type"] == "boolean" and questions["team"]["type"] == "choice"
                return {"n_tokens": 42, "latency_ms": 20.0, "answers": {
                    "risky": {"probs": {"False": 0.3, "True": 0.7}, "confidence": 0.7, "boolean": 0.7,
                              "prediction_set": [False, True], "abstain": False, "unbound": False},
                    "team": {"probs": {"billing": 0.9, "tech": 0.1}, "confidence": 0.9, "choice": "billing",
                             "prediction_set": ["billing"], "abstain": False, "unbound": False}}}

        resp = self.vs.handle_request(StubEngine(), "vega-0.8b@abc", {
            "state": {"diff": "+x"},
            "questions": {"risky": {"type": "noul", "instructions": "risky?"},
                          "team": {"type": "choice", "instructions": "which?",
                                   "criteria": {"billing": "money", "tech": "bugs"}}}})
        self.assertEqual(resp["model"], "vega-0.8b@abc")
        self.assertEqual(resp["usage"], {"input_tokens": 42, "output_tokens": 0})
        self.assertEqual(resp["answers"]["risky"]["noul"], 0.7)
        self.assertEqual(resp["answers"]["risky"]["prediction_set"], ["false", "true"])
        self.assertEqual(resp["answers"]["team"]["choice"], "billing")
        # and the gate understands what the wrapper produces
        spec = importlib.util.spec_from_file_location(
            "dg", os.path.join(KIT, "template", ".claude", "god", "decide", "decision_gate.py"))
        dg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dg)
        n = dg.normalize_answer("noul", resp["answers"]["risky"])
        self.assertEqual((n["value"], n["set_size"]), (0.7, 2))

    def test_rejects_bad_requests(self):
        for body in ({}, {"state": "x", "questions": {}},
                     {"state": "x", "questions": {"a": {"type": "essay", "instructions": "?"}}},
                     {"state": "x", "questions": {"a": {"type": "choice", "instructions": "?"}}}):
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    self.vs.handle_request(None, "m", body)


if __name__ == "__main__":
    unittest.main()
