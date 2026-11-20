"""Opt-in WSL client for the IAM-invoked Sydney Laya decision pilot."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import decision_gate as gate

REGION = "ap-southeast-2"
FUNCTION = "limpid-laya-decisions"
MODEL = "laya-typed-decisions"
AWS_PROVIDER = {"name": "laya-aws", "url": f"https://lambda.{REGION}.amazonaws.com",
                "expected_model": MODEL, "allow_remote_in_private_repo": False}
KINDS = ("bugfix", "tests", "implementation", "review")
SCOPES = ("small", "medium", "large")
TIERS = {
    "quick": "A focused edit or targeted test with clear requirements.",
    "deep": "A complex debugging or implementation task that needs stronger reasoning.",
    "review": "An independent review or a change that needs extra scrutiny.",
}


def aws(profile, region, *args):
    env = dict(os.environ, AWS_PAGER="", AWS_MAX_ATTEMPTS="1", AWS_CLI_AUTO_PROMPT="off",
               AWS_IGNORE_CONFIGURED_ENDPOINT_URLS="true", AWS_EC2_METADATA_DISABLED="true")
    try:
        result = subprocess.run(
            ["aws", "--profile", profile, "--region", region, "--output", "json",
             "--cli-connect-timeout", "5", "--cli-read-timeout", "125", *args],
            capture_output=True, text=True, timeout=135, env=env, check=True,
        )
        return json.loads(result.stdout)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        operation = " ".join(args[:2])
        raise gate.ModelUnavailable(f"AWS {operation} failed. Check aws login and the Sydney Laya stack.") from error


def invoke(state, questions):
    profile = os.environ.get("GOD_AWS_PROFILE", "").strip()
    if not profile:
        raise gate.ModelUnavailable("Set GOD_AWS_PROFILE to your WSL AWS login profile.")
    plan = aws(profile, "us-east-1", "freetier", "get-account-plan-state")
    if plan.get("accountPlanType") != "FREE" or plan.get("accountPlanStatus") != "ACTIVE":
        raise gate.ModelUnavailable("Laya pilot requires an active AWS Free Plan.")
    request = json.dumps({"state": state, "questions": questions, "model": MODEL}, ensure_ascii=False).encode()
    if len(request) > 32 * 1024:
        raise gate.ModelUnavailable("Laya request exceeds 32 KiB.")
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="god-laya-") as scratch:
        src, dst = Path(scratch) / "request.json", Path(scratch) / "answer.json"
        src.write_bytes(request)
        result = aws(profile, REGION, "lambda", "invoke", "--function-name", FUNCTION,
                     "--payload", f"fileb://{src}", str(dst))
        if result.get("StatusCode") != 200 or result.get("FunctionError"):
            raise gate.ModelUnavailable("Laya Lambda invocation failed.")
        try:
            with dst.open("rb") as fh:
                response = json.loads(fh.read(262145), parse_constant=gate._reject_constant)
        except (OSError, ValueError) as exc:
            raise gate.ModelUnavailable("Laya returned an unreadable response.") from exc
    if not isinstance(response, dict):
        raise gate.ModelUnavailable("Laya returned an invalid response.")
    if response.get("code") == "quota":
        raise gate.ModelUnavailable("Monthly Laya decision cap reached.")
    answers = response.get("answers")
    if response.get("model") != MODEL or not isinstance(answers, dict) or set(questions) - set(answers):
        raise gate.ModelUnavailable("Laya did not answer every requested question.")
    return response, round((time.monotonic() - start) * 1000, 1)


def route(kind, scope):
    # Only fixed metadata enters a routing request. This command does not inspect a repository.
    if kind not in KINDS or scope not in SCOPES:
        raise ValueError("Expected a supported task type and scope.")
    state = f"Coding task type: {kind}\nChange scope: {scope}"
    questions = {"tier": {"type": "choice", "instructions": "Which capability does this coding task require?",
                          "criteria": TIERS}}
    response, _ = invoke(state, questions)
    answer = gate.normalize_answer("choice", response["answers"]["tier"])
    if (answer["abstain"] or answer["unbound"] or (answer["set_size"] or 0) > 1
            or answer["confidence"] < 0.7 or answer["value"] not in TIERS):
        return "review", "Laya was uncertain"
    return answer["value"], "Laya advisory recommendation"


def check(root, goal, base):
    cfg = gate.load_config(root)
    if gate.is_private_repo(root, cfg):
        raise gate.GateError("AWS Laya patch checks require an explicitly public repository.")
    if not cfg["checks"]:
        raise gate.GateError("Configure local test commands under checks in .ai/decision-gate.json.")
    return gate.gate_check(root, goal, base, advisory_provider=AWS_PROVIDER,
                           model_call=lambda _cfg, state, questions: invoke(state, questions))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    advice = commands.add_parser("route", help="recommend a model capability from task metadata")
    advice.add_argument("--kind", choices=KINDS, required=True)
    advice.add_argument("--scope", choices=SCOPES, required=True)
    patch = commands.add_parser("check", help="run local checks, then ask Laya about a public patch")
    patch.add_argument("--public", action="store_true", required=True, help="approve sending the public patch to AWS")
    patch.add_argument("--goal")
    patch.add_argument("--base")
    args = parser.parse_args(argv)
    try:
        if args.command == "route":
            tier, reason = route(args.kind, args.scope)
            print(f"Recommended capability: {tier} ({reason}).")
            return 0
        receipt, _ = check(gate.find_root(), args.goal, args.base)
        gate.print_check(receipt, None)
        return 1 if receipt["verdict"] in (gate.NOT_READY, gate.UNAVAILABLE) else 0
    except (gate.GateError, gate.ModelUnavailable, ValueError) as error:
        print(f"Laya: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
