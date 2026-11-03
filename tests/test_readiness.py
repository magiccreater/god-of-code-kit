"""Tests for task readiness (readiness.py), its pre-tool guard, the decision-gate link and the installer's
handling of edited kit files.

No model or network needed:  python3 -m unittest -v tests/test_readiness.py
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "tests"))
sys.path.insert(0, os.path.join(KIT, "template", ".claude", "god", "decide"))
sys.path.insert(0, os.path.join(KIT, "kit"))
from test_decision_gate import GOOD, FakeServer, sh  # noqa: E402
import readiness as rd  # noqa: E402
import kit_files  # noqa: E402

READINESS = os.path.join(".claude", "god", "decide", "readiness.py")
GATE = os.path.join(".claude", "god", "decide", "decision_gate.py")
GUARD = os.path.join(".claude", "god", "hooks", "pretool_guard.sh")
CFG = dict(rd.DEFAULT_CONFIG)


def spec(meta, **sections):
    """Build a spec: spec({"type": "bug"}, why="...", steps_to_reproduce="1. a\\n2. b")."""
    head = "---\n" + "".join("%s: %s\n" % kv for kv in meta.items()) + "---\n\n# Task\n\n"
    body = "".join("## %s\n%s\n\n" % (k.replace("_", " ").capitalize(), v) for k, v in sections.items())
    return head + body


FULL_FEATURE = dict(
    why="Support staff refund whole orders only; customers who return one item wait days for a manual fix.",
    what="Add a partial refund action to the order admin screen and POST /orders/{id}/refunds.",
    out_of_scope="Refunds to a different payment method.",
    requirements="- FR-001: Staff MUST be able to refund part of a captured payment.\n"
                 "- FR-002: The system MUST NOT refund more than the remaining captured amount.",
    acceptance_criteria=(
        "- AC-001 (FR-001): Given a captured order of $100, When staff refund $30, Then the payment provider "
        "receives a $30 refund and the order shows \"Partially refunded\".\n"
        "- AC-002 (FR-002): Given $70 remains refundable, When staff try to refund $80, Then the request is "
        "rejected with status 422 and nothing is sent to the provider."),
    edge_cases="Two refunds submitted at once; currency rounding to cents.",
    non_functional="none",
    dependencies_and_access="Stripe test keys in the staging vault.",
)

FULL_BUG = dict(
    why="Customers are charged twice when they double-click Pay.",
    steps_to_reproduce="1. Open checkout on staging with a test card\n2. Double-click Pay quickly\n"
                       "3. Open the Stripe dashboard",
    expected="One charge of the order total.",
    actual="Two identical charges with different payment intents.",
    environment="staging, release 4.12.0, Chrome 131",
    evidence="Stripe events evt_1 and evt_2 at 10:42:01 for order 5521.",
    impact="About 3 orders a day since 4.12.0.",
    acceptance_criteria="- AC-001: Given a checkout, When Pay is submitted twice within 2 seconds, Then exactly "
                        "one charge is created.",
    dependencies_and_access="none",
)


def item(result, item_id):
    return next(i for i in result["items"] if i["id"] == item_id)


class TestScoring(unittest.TestCase):
    def test_full_feature_is_ready(self):
        r = rd.score_spec(spec({"type": "feature"}, **FULL_FEATURE), CFG)
        self.assertEqual(r["verdict"], rd.READY, r["items"])
        self.assertEqual(r["score"], 100)

    def test_vague_ticket_is_not_ready_with_at_most_five_questions(self):
        r = rd.score_spec(spec({"type": "feature"}, why="Customers want it.",
                               what="Add partial refunds. Make it fast and user friendly."), CFG)
        self.assertEqual(r["verdict"], rd.NOT_READY)
        self.assertLessEqual(len(r["questions"]), 5)
        self.assertTrue(any("acceptance criteria" in q for q in r["questions"]))
        self.assertEqual(item(r, "acceptance")["status"], "missing")

    def test_placeholders_and_comments_count_as_empty(self):
        text = rd.new_spec_text("T-001", "feature", "Refunds", "normal")
        r = rd.score_spec(text.replace("## Why\n", "## Why\nTBD\n"), CFG)
        self.assertEqual(item(r, "why")["status"], "missing")
        self.assertEqual(r["score"], 0)

    def test_vague_acceptance_criterion_is_weak(self):
        f = dict(FULL_FEATURE, acceptance_criteria="- AC-001 (FR-001): The refund page is fast and user friendly.\n"
                 "- AC-002 (FR-002): Given $70 remains, When staff refund $80, Then it is rejected with status 422.")
        r = rd.score_spec(spec({"type": "feature"}, **f), CFG)
        ac = item(r, "acceptance")
        self.assertEqual(ac["status"], "weak")
        self.assertIn("AC-001", ac["message"])
        self.assertIn("fast", ac["message"])
        self.assertEqual(r["verdict"], rd.NEEDS_INFO)  # acceptance is a must for features

    def test_requirement_without_acceptance_criterion_is_flagged(self):
        f = dict(FULL_FEATURE, acceptance_criteria=FULL_FEATURE["acceptance_criteria"].split("\n")[0])
        r = rd.score_spec(spec({"type": "feature"}, **f), CFG)
        self.assertEqual(item(r, "fr_coverage")["status"], "weak")
        self.assertIn("FR-002", item(r, "fr_coverage")["message"])

    def test_none_is_a_valid_answer_only_where_allowed(self):
        r = rd.score_spec(spec({"type": "feature"}, **dict(FULL_FEATURE, edge_cases="None")), CFG)
        self.assertEqual(item(r, "edge_cases")["status"], "ok")
        r = rd.score_spec(spec({"type": "feature"}, **dict(FULL_FEATURE, why="none")), CFG)
        self.assertNotEqual(item(r, "why")["status"], "ok")

    def test_open_clarification_blocks_ready(self):
        f = dict(FULL_FEATURE, open_questions="[NEEDS CLARIFICATION: may staff refund shipping costs]")
        r = rd.score_spec(spec({"type": "feature"}, **f), CFG)
        self.assertEqual(r["verdict"], rd.NEEDS_INFO)
        self.assertEqual(r["score"], 100)
        self.assertEqual(r["questions"][0], "may staff refund shipping costs?")

    def test_full_bug_is_ready(self):
        r = rd.score_spec(spec({"type": "bug"}, **FULL_BUG), CFG)
        self.assertEqual(r["verdict"], rd.READY, r["items"])

    def test_bug_needs_numbered_steps_and_distinct_actual(self):
        b = dict(FULL_BUG, steps_to_reproduce="Double-click pay.", actual="One charge of the order total.")
        r = rd.score_spec(spec({"type": "bug"}, **b), CFG)
        self.assertEqual(item(r, "steps")["status"], "weak")
        self.assertEqual(item(r, "actual")["status"], "weak")
        self.assertEqual(r["verdict"], rd.NEEDS_INFO)
        self.assertTrue(r["questions"][0].startswith("What are the exact steps"))

    def test_bug_without_environment_is_not_ready_to_start(self):
        b = dict(FULL_BUG)
        del b["environment"]
        r = rd.score_spec(spec({"type": "bug"}, **b), CFG)
        self.assertEqual(item(r, "environment")["status"], "missing")
        self.assertEqual(r["verdict"], rd.NEEDS_INFO)

    def test_vague_evidence_is_weak(self):
        r = rd.score_spec(spec({"type": "bug"}, **dict(FULL_BUG, evidence="It errors.")), CFG)
        self.assertEqual(item(r, "evidence")["status"], "weak")

    def test_high_risk_needs_rollback(self):
        r = rd.score_spec(spec({"type": "feature", "risk": "high"}, **FULL_FEATURE), CFG)
        self.assertEqual(item(r, "rollback")["status"], "missing")
        self.assertEqual(r["verdict"], rd.NEEDS_INFO)
        r = rd.score_spec(spec({"type": "feature", "risk": "high"}, rollback="Turn off the refunds_partial flag; "
                               "no data migration.", reviewers="Payments lead", **FULL_FEATURE), CFG)
        self.assertEqual(r["verdict"], rd.READY, r["items"])

    def test_type_specific_must_haves(self):
        r = rd.score_spec(spec({"type": "refactor"}, why="Split the 900-line OrderService.",
                               what="Move refund logic into RefundService."), CFG)
        ids = {i["id"]: i for i in r["items"]}
        self.assertEqual(ids["must_not_change"]["level"], "must")
        self.assertEqual(ids["safety_net"]["status"], "missing")
        self.assertNotIn("steps", ids)
        r = rd.score_spec(spec({"type": "chore"}, why="Security fixes in the new minor.",
                               what="Upgrade Laravel 11.30 to 11.34."), CFG)
        self.assertEqual(r["verdict"], rd.READY)

    def test_unknown_type_is_not_ready(self):
        r = rd.score_spec(spec({"type": "story"}, **FULL_FEATURE), CFG)
        self.assertEqual(r["verdict"], rd.NOT_READY)
        self.assertIn("type", r["blockers"][0])

    def test_skip_drops_an_item(self):
        cfg = dict(CFG, skip={"rollback": "feature flags cover it"})
        r = rd.score_spec(spec({"type": "feature", "risk": "high"}, reviewers="me", **FULL_FEATURE), cfg)
        self.assertNotIn("rollback", [i["id"] for i in r["items"]])
        self.assertEqual(r["verdict"], rd.READY)

    def test_new_spec_has_type_sections(self):
        text = rd.new_spec_text("T-007", "bug", "Double charge", "high")
        for h in ("## Steps to reproduce", "## Expected", "## Actual", "## Environment", "## Rollback",
                  "## Convergence"):
            self.assertIn(h, text)
        self.assertNotIn("## Requirements", text)
        self.assertEqual(rd.parse_front_matter(text)[0]["risk"], "high")

    def test_spec_goal_and_testable_helpers(self):
        goal = rd.spec_goal(spec({"type": "feature", "title": "Partial refunds"}, **FULL_FEATURE))
        self.assertTrue(goal.startswith("Partial refunds (feature)"))
        self.assertIn("AC-002", goal)
        self.assertTrue(rd.ac_is_testable("Then the API returns 404")[0])
        self.assertFalse(rd.ac_is_testable("It works correctly and is fast")[0])


class RepoBase(unittest.TestCase):
    """A git repo with the kit installed and one source file."""

    install_args = ()

    @classmethod
    def setUpClass(cls):
        cls.server = FakeServer()

    @classmethod
    def tearDownClass(cls):
        cls.server.close()

    def setUp(self):
        self.server.requests.clear()
        self.server.behavior = {"answers": GOOD, "model": "fake-1.0"}
        self.repo = tempfile.mkdtemp(prefix="ready-")
        sh(self.repo, "git", "init", "-q", "-b", "main")
        sh(self.repo, "git", "config", "user.email", "t@t")
        sh(self.repo, "git", "config", "user.name", "t")
        os.makedirs(os.path.join(self.repo, "app"))
        self.write("app/refunds.py", "def refund(order, amount):\n    raise NotImplementedError\n")
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-qm", "base")
        sh(self.repo, "bash", os.path.join(KIT, "install.sh"), self.repo, *self.install_args)
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-qm", "kit", "--allow-empty")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def read(self, rel):
        with open(os.path.join(self.repo, rel)) as fh:
            return fh.read()

    def env(self, **kw):
        e = dict(os.environ, CLAUDE_PROJECT_DIR=self.repo)
        for k in ("GOD_GATE_MODE", "GOD_READINESS_MODE"):
            e.pop(k, None)
        e.update(kw)
        return e

    def run_rd(self, *args, **envkw):
        r = sh(self.repo, sys.executable, READINESS, *args, check=False, env=self.env(**envkw))
        if "--json" in args:
            try:
                return r.returncode, json.loads(r.stdout)
            except ValueError:
                raise AssertionError("not JSON (exit %d): %s %s" % (r.returncode, r.stdout, r.stderr))
        return r.returncode, r.stdout + r.stderr

    def set_config(self, **kw):
        cfg = json.loads(self.read(".ai/readiness.json"))
        cfg.update(kw)
        self.write(".ai/readiness.json", json.dumps(cfg, indent=2))

    def set_current_task(self, task):
        text = self.read(".ai/memory/state.md")
        self.write(".ai/memory/state.md", re.sub(r"\*\*Current task\*\*:.*", "**Current task**: " + task, text))

    def put_spec(self, task, text):
        self.write(".ai/specs/%s/spec.md" % task, text)

    def guard(self, tool, **tool_input):
        payload = json.dumps({"tool_name": tool, "cwd": self.repo, "tool_input": tool_input})
        r = subprocess.run(["bash", GUARD], cwd=self.repo, input=payload, capture_output=True, text=True,
                           env=self.env())
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def edit_guard(self, rel):
        return self.guard("Edit", file_path=os.path.join(self.repo, rel), old_string="a", new_string="b")


class TestCommands(RepoBase):
    def test_installed_defaults(self):
        cfg = json.loads(self.read(".ai/readiness.json"))
        self.assertEqual((cfg["mode"], cfg["ready_score"]), ("advisory", 80))
        self.assertTrue(os.path.exists(os.path.join(self.repo, ".ai", "specs", "README.md")))
        for skill in ("task-ready", "converge"):
            self.assertTrue(os.path.exists(os.path.join(self.repo, ".claude", "skills", skill, "SKILL.md")))
        code, out = self.run_rd("status")
        self.assertEqual(code, 0, out)
        self.assertIn("Mode: advisory", out)

    def test_new_check_record_and_staleness(self):
        code, out = self.run_rd("new", "T-001", "--type", "feature", "--title", "Partial refunds")
        self.assertEqual(code, 0, out)
        code, out = self.run_rd("new", "T-001", "--type", "feature", "--title", "Again")
        self.assertEqual(code, 2)
        self.assertIn("already exists", out)
        code, rec = self.run_rd("check", "T-001", "--json")
        self.assertEqual((code, rec["verdict"]), (0, rd.NOT_READY))  # advisory never fails
        self.put_spec("T-001", spec({"id": "T-001", "type": "feature", "title": "Partial refunds"}, **FULL_FEATURE))
        code, rec = self.run_rd("check", "T-001", "--json")
        self.assertEqual(rec["verdict"], rd.READY)
        self.assertEqual(rec["record_path"], ".ai/review/readiness/T-001.json")
        self.assertEqual(self.run_rd("verify", "T-001")[0], 0)
        self.put_spec("T-001", self.read(".ai/specs/T-001/spec.md") + "\n## Answers\n- 2026-11-03: yes\n")
        code, out = self.run_rd("verify", "T-001")
        self.assertEqual(code, 1)
        self.assertIn("spec changed", out)

    def test_current_task_is_the_default(self):
        self.put_spec("T-002", spec({"type": "bug"}, **FULL_BUG))
        code, out = self.run_rd("check")
        self.assertEqual(code, 2)
        self.assertIn("Current task", out)
        self.set_current_task("T-002")
        code, rec = self.run_rd("check", "--json")
        self.assertEqual((rec["task"], rec["verdict"]), ("T-002", rd.READY))

    def test_required_mode_exit_code_and_off_mode(self):
        self.put_spec("T-003", spec({"type": "feature"}, why="Customers want it."))
        self.assertEqual(self.run_rd("check", "T-003", GOD_READINESS_MODE="required")[0], 1)
        code, rec = self.run_rd("check", "T-003", "--json", GOD_READINESS_MODE="off")
        self.assertEqual((code, rec["verdict"]), (0, rd.OFF))

    def test_bad_config_is_reported(self):
        self.set_config(ready_score=40, ask_score=60)
        code, out = self.run_rd("status")
        self.assertEqual(code, 2)
        self.assertIn("ask_score", out)
        self.set_config(ready_score=80, ask_score=50, skip={"nonsense": "x"})
        self.assertIn("unknown items", self.run_rd("status")[1])

    def test_trace_finds_tests_named_after_criteria(self):
        self.put_spec("T-004", spec({"type": "feature"}, **FULL_FEATURE))
        self.write("tests/test_refunds.py", "def test_ac_001_partial_refund():\n    assert True\n")
        code, t = self.run_rd("trace", "T-004", "--json")
        self.assertEqual(code, 1)
        self.assertEqual([c["id"] for c in t["covered"]], ["AC-001"])
        self.assertEqual([c["id"] for c in t["uncovered"]], ["AC-002"])
        self.write("tests/refunds.test.ts", "it('AC-2 rejects refunds above the balance', () => {})\n")
        code, t = self.run_rd("trace", "T-004", "--json")
        self.assertEqual((code, t["uncovered"]), (0, []))
        self.assertFalse(t["converged"])


class TestModelLayer(RepoBase):
    def setUp(self):
        super().setUp()
        cfg = json.loads(self.read(".ai/decision-gate.json"))
        cfg["provider"].update(url="http://127.0.0.1:%d" % self.server.port, timeout_seconds=2)
        self.write(".ai/decision-gate.json", json.dumps(cfg))
        self.set_config(model={"enabled": True, "min_confidence": 0.7})
        self.put_spec("T-010", spec({"type": "feature"}, **FULL_FEATURE))

    def test_model_can_lower_but_not_raise(self):
        self.server.behavior["answers"] = {"criteria_cover_goal": {"noul": 0.92, "confidence": 0.92}}
        code, rec = self.run_rd("check", "T-010", "--json")
        self.assertEqual(rec["verdict"], rd.READY)
        sent = self.server.requests[-1]["body"]
        self.assertIn("criteria_cover_goal", sent["questions"])
        self.assertIn("AC-001", sent["state"]["task_spec"])
        self.server.behavior["answers"] = {"criteria_cover_goal": {"noul": 0.2, "confidence": 0.9}}
        code, rec = self.run_rd("check", "T-010", "--json")
        self.assertEqual(rec["verdict"], rd.NEEDS_INFO)
        self.assertTrue(any("not yet covered" in q for q in rec["questions"]))
        self.put_spec("T-011", spec({"type": "feature"}, why="Customers want it."))
        self.server.behavior["answers"] = {"criteria_cover_goal": {"noul": 0.99, "confidence": 0.99}}
        self.assertEqual(self.run_rd("check", "T-011", "--json")[1]["verdict"], rd.NOT_READY)

    def test_unsure_model_is_not_ready(self):
        self.server.behavior["answers"] = {"criteria_cover_goal": {"noul": 0.9, "confidence": 0.5}}
        self.assertEqual(self.run_rd("check", "T-010", "--json")[1]["verdict"], rd.NEEDS_INFO)

    def test_model_down_is_a_note_not_a_failure(self):
        self.server.behavior["status"] = 500
        code, rec = self.run_rd("check", "T-010", "--json")
        self.assertEqual(rec["verdict"], rd.READY)
        self.assertTrue(any("unavailable" in n for n in rec["model_notes"]))


class TestPrivateModelLayer(RepoBase):
    install_args = ("--private",)

    def test_remote_model_refused_in_private_repo(self):
        cfg = json.loads(self.read(".ai/decision-gate.json"))
        cfg["provider"]["url"] = "https://api.example.com"
        self.write(".ai/decision-gate.json", json.dumps(cfg))
        self.set_config(model={"enabled": True})
        self.put_spec("T-012", spec({"type": "feature"}, **FULL_FEATURE))
        code, rec = self.run_rd("check", "T-012", "--json")
        self.assertTrue(any("refused" in n for n in rec["model_notes"]))
        self.assertEqual(self.server.requests, [])


class TestGuard(RepoBase):
    def test_advisory_never_blocks_edits(self):
        self.assertIsNone(self.edit_guard("app/refunds.py"))

    def test_required_mode_blocks_source_edits_until_ready(self):
        self.set_config(mode="required")
        d = self.edit_guard("app/refunds.py")
        self.assertEqual(d["permissionDecision"], "deny")
        self.assertIn("Current task", d["permissionDecisionReason"])
        self.set_current_task("T-020")
        self.assertIn("no readiness check", self.edit_guard("app/refunds.py")["permissionDecisionReason"])
        self.put_spec("T-020", spec({"type": "feature"}, why="Customers want it."))
        self.run_rd("check", "T-020")
        self.assertIn("not_ready", self.edit_guard("app/refunds.py")["permissionDecisionReason"])
        # tests, docs and the brain are always editable, so the spec can be completed
        self.assertIsNone(self.edit_guard("tests/test_refunds.py"))
        self.assertIsNone(self.edit_guard(".ai/specs/T-020/spec.md"))
        self.assertIsNone(self.edit_guard("README.md"))
        self.put_spec("T-020", spec({"type": "feature"}, **FULL_FEATURE))
        self.run_rd("check", "T-020")
        self.assertIsNone(self.edit_guard("app/refunds.py"))
        self.put_spec("T-020", spec({"type": "feature"}, **dict(FULL_FEATURE, edge_cases="Refund of $0.")))
        self.assertIn("stale", self.edit_guard("app/refunds.py")["permissionDecisionReason"])
        self.run_rd("check", "T-020")
        d = self.guard("Bash", command="echo x > app/refunds.py")
        self.assertIsNone(d)

    def test_required_mode_covers_shell_writes(self):
        self.set_config(mode="required")
        d = self.guard("Bash", command="sed -i 's/a/b/' app/refunds.py")
        self.assertEqual(d["permissionDecision"], "deny")

    def test_config_and_record_edits_ask(self):
        d = self.guard("Write", file_path=os.path.join(self.repo, ".ai/readiness.json"), content="{}")
        self.assertEqual(d["permissionDecision"], "ask")
        d = self.guard("Write", file_path=os.path.join(self.repo, ".ai/review/readiness/T-1.json"), content="{}")
        self.assertEqual(d["permissionDecision"], "ask")
        d = self.guard("Bash", command="rm .ai/readiness.json")
        self.assertEqual(d["permissionDecision"], "ask")

    def test_broken_config_asks_instead_of_blocking_silently(self):
        self.write(".ai/readiness.json", "{not json")
        self.assertEqual(self.edit_guard("app/refunds.py")["permissionDecision"], "ask")


class TestRefundScenario(RepoBase):
    """End to end: vague ticket -> questions -> full spec -> ready -> partial build -> gate needs_review -> done."""

    def gate(self):
        r = sh(self.repo, sys.executable, GATE, "check", "--json", check=False, env=self.env())
        return json.loads(r.stdout)

    def test_refund_feature(self):
        cfg = json.loads(self.read(".ai/decision-gate.json"))
        cfg.update(mode="advisory", checks=["python3 -c \"print('tests ok')\""])
        cfg["provider"].update(url="http://127.0.0.1:%d" % self.server.port, timeout_seconds=2)
        self.write(".ai/decision-gate.json", json.dumps(cfg))
        self.set_config(mode="required")
        self.set_current_task("T-031")

        # 1. the ticket as it usually arrives
        self.run_rd("new", "T-031", "--type", "feature", "--title", "Partial refunds", "--risk", "high")
        text = self.read(".ai/specs/T-031/spec.md")
        text = text.replace("## Why\n", "## Why\nCustomers want partial refunds.\n").replace(
            "## What\n", "## What\nAdd partial refunds. It should be fast and user friendly.\n")
        self.put_spec("T-031", text)
        code, rec = self.run_rd("check", "--json")
        self.assertEqual((code, rec["verdict"]), (1, rd.NOT_READY))
        self.assertTrue(1 <= len(rec["questions"]) <= 5)
        self.assertEqual(self.edit_guard("app/refunds.py")["permissionDecision"], "deny")

        # 2. the answers go into the spec
        self.put_spec("T-031", spec({"id": "T-031", "type": "feature", "title": "Partial refunds", "risk": "high"},
                                    rollback="Turn off the refunds_partial flag.", reviewers="Payments lead",
                                    **FULL_FEATURE))
        code, rec = self.run_rd("check", "--json")
        self.assertEqual((code, rec["verdict"]), (0, rd.READY))
        self.assertIsNone(self.edit_guard("app/refunds.py"))

        # 3. a partial build: AC-001 tested, AC-002 forgotten
        self.write("app/refunds.py", "def refund(order, amount):\n    order.refunded += amount\n")
        self.write("tests/test_refunds.py", "def test_ac_001_partial_refund():\n    assert True\n")
        g = self.gate()
        self.assertEqual(g["verdict"], "needs_review")
        self.assertEqual(g["task"]["uncovered"], ["AC-002"])
        self.assertTrue(any("AC-002" in r for r in g["reasons"]))
        self.assertTrue(any("/converge" in a for a in g["advice"]))
        goal_sent = self.server.requests[-1]["body"]["state"]["task_goal"]
        self.assertIn("Partial refunds", goal_sent)
        self.assertIn("AC-002", goal_sent)

        # 4. the gap is closed and converge records it
        self.write("tests/test_refunds.py", "def test_ac_001_partial_refund():\n    assert True\n\n\n"
                                            "def test_ac_002_rejects_refund_above_balance():\n    assert True\n")
        self.put_spec("T-031", self.read(".ai/specs/T-031/spec.md") +
                      "## Convergence\n- 2026-11-03: converged — 2/2 AC tested, 0 gaps\n")
        g = self.gate()
        self.assertEqual(g["verdict"], "ready", g["reasons"])
        self.assertTrue(g["task"]["converged"])

    def test_gate_without_spec_is_unchanged(self):
        self.write("app/refunds.py", "def refund(order, amount):\n    return amount\n")
        cfg = json.loads(self.read(".ai/decision-gate.json"))
        cfg.update(mode="advisory", checks=["true"])
        cfg["provider"].update(url="http://127.0.0.1:%d" % self.server.port, timeout_seconds=2)
        self.write(".ai/decision-gate.json", json.dumps(cfg))
        g = self.gate()
        self.assertNotIn("task", g)


class TestKitFileUpgrades(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="kitup-")
        self.template = os.path.join(KIT, "template")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def install(self):
        r = sh(self.repo, "bash", os.path.join(KIT, "install.sh"), self.repo)
        return r.stdout

    def test_edited_kit_file_is_kept_and_unedited_is_upgraded(self):
        self.install()
        skill = os.path.join(self.repo, ".claude", "skills", "ready-gate", "SKILL.md")
        agent = os.path.join(self.repo, ".claude", "agents", "code-reviewer.md")
        with open(skill, "a") as fh:
            fh.write("\nOur team: also run the e2e suite.\n")
        # simulate an older kit version of the agent that the user never touched
        old = "old kit version\n"
        with open(agent, "w") as fh:
            fh.write(old)
        manifest = os.path.join(self.repo, kit_files.MANIFEST_REL)
        with open(manifest) as fh:
            m = json.load(fh)
        m["files"][".claude/agents/code-reviewer.md"] = hashlib.sha256(old.encode()).hexdigest()
        with open(manifest, "w") as fh:
            json.dump(m, fh)
        out = self.install()
        self.assertIn("keep     .claude/skills/ready-gate/SKILL.md", out)
        self.assertIn("upgrade  .claude/agents/code-reviewer.md", out)
        with open(skill) as fh:
            self.assertIn("Our team", fh.read())
        self.assertTrue(os.path.exists(skill + ".kit-new"))
        with open(agent) as fh, open(os.path.join(self.template, ".claude", "agents", "code-reviewer.md")) as src:
            self.assertEqual(fh.read(), src.read())
        # merging by hand (making it identical) clears the leftover .kit-new on the next run
        shutil.copy(os.path.join(self.template, ".claude", "skills", "ready-gate", "SKILL.md"), skill)
        out = self.install()
        self.assertFalse(os.path.exists(skill + ".kit-new"))
        self.assertIn("0 kept", out)

    def test_install_without_manifest_upgrades_shipped_versions(self):
        """Repos installed before the manifest existed: a file equal to any shipped version is upgraded."""
        self.install()
        os.remove(os.path.join(self.repo, kit_files.MANIFEST_REL))
        rel = ".claude/god/decide/decision_gate.py"
        old = sh(KIT, "git", "show", "4d594ec:template/" + rel).stdout  # as shipped by the previous release
        with open(os.path.join(self.repo, rel), "w") as fh:
            fh.write(old)
        tweaked = ".claude/god/hooks/pretool_guard.py"
        with open(os.path.join(self.repo, tweaked), "a") as fh:
            fh.write("# local tweak\n")
        out = self.install()
        self.assertIn("upgrade  %s" % rel, out)
        self.assertIn("keep     %s" % tweaked, out)

    def test_shipped_list_covers_current_kit_files(self):
        """Regenerate with: python3 kit/kit_files.py shipped . > kit/shipped.sha256"""
        shipped = kit_files.load_shipped()
        missing = [rel for rel, full in kit_files.kit_files(self.template)
                   if kit_files.sha256_file(full) not in shipped.get(rel, ())]
        self.assertEqual(missing, [], "kit/shipped.sha256 is out of date")

    def test_private_mode_excludes_new_skills(self):
        sh(self.repo, "git", "init", "-q")
        sh(self.repo, "bash", os.path.join(KIT, "install.sh"), self.repo, "--private")
        with open(os.path.join(self.repo, ".git", "info", "exclude")) as fh:
            ex = fh.read().split()
        for skill in os.listdir(os.path.join(self.template, ".claude", "skills")):
            self.assertIn(".claude/skills/%s/" % skill, ex)
        self.assertEqual(sh(self.repo, "git", "status", "--porcelain").stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
