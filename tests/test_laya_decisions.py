from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "template/.claude/god/decide"))
import laya_decision as laya


class LayaDecisionTest(unittest.TestCase):
    def test_route_sends_fixed_metadata_and_abstains_on_low_confidence(self):
        low = {"answers": {"tier": {"choice": "deep", "probabilities": {"deep": 0.6}}}}
        with patch.object(laya, "invoke", return_value=(low, 5)) as request:
            tier, _ = laya.route("bugfix", "small")
            self.assertEqual(tier, "review")
            self.assertEqual(request.call_args.args[0], "Coding task type: bugfix\nChange scope: small")
            with self.assertRaises(ValueError):
                laya.route("Raw task text", "small")
            request.assert_called_once()

    def test_public_patch_check_refuses_private_config(self):
        with patch.object(laya.gate, "load_config", return_value={"private": True}), patch.object(
            laya.gate, "gate_check"
        ) as gate_check:
            with self.assertRaisesRegex(laya.gate.GateError, "public repository"):
                laya.check("/irrelevant", None, None)
            gate_check.assert_not_called()

    def test_paid_plan_never_invokes_laya(self):
        with patch.dict("os.environ", {"GOD_AWS_PROFILE": "sample"}), patch.object(
            laya, "aws", return_value={"accountPlanType": "PAID", "accountPlanStatus": "ACTIVE"}
        ) as aws:
            with self.assertRaisesRegex(laya.gate.ModelUnavailable, "active AWS Free Plan"):
                laya.invoke("Test.", {})
            aws.assert_called_once_with("sample", "us-east-1", "freetier", "get-account-plan-state")
