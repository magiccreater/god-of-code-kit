import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from argparse import Namespace
from datetime import datetime, timezone
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "template/.claude/god/worker"))
from aws_gateway import AwsGateway, GatewayError, sign_headers
from chat_responses import chat_request, response_events
import run

URL = "https://test123.execute-api.ap-southeast-2.amazonaws.com/pilot/v1"
CREDENTIALS = {"AccessKeyId": "FAKEACCESS", "SecretAccessKey": "FAKESECRET", "SessionToken": "TOKEN"}


def data_event(delta, finish_reason=None):
    payload = {"choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}]}
    return b"data: " + json.dumps(payload).encode() + b"\n\n"


DONE = b"data: [DONE]\n\n"


class GatewayTests(unittest.TestCase):
    def test_route_requires_an_explicit_public_choice(self):
        self.assertEqual(AwsGateway(URL, CREDENTIALS).model, "private-coder")
        self.assertEqual(AwsGateway(URL, CREDENTIALS, public=True).model, "private-coder-public")
        for invalid in (URL.replace("ap-southeast-2", "us-east-1"), URL + "?extra=1",
                        "https://outside.example/pilot/v1", URL.replace("https", "http")):
            with self.assertRaises(GatewayError):
                AwsGateway(invalid, CREDENTIALS)
        with self.assertRaises(GatewayError):
            AwsGateway(URL, {key: value for key, value in CREDENTIALS.items() if key != "SessionToken"})

    def test_paid_project_is_rejected_before_stack_discovery(self):
        with patch("aws_gateway.cli", return_value={"accountPlanType": "PAID", "accountPlanStatus": "ACTIVE"}) as aws:
            with self.assertRaisesRegex(GatewayError, "active AWS Free Plan"):
                AwsGateway.discover("sample")
            aws.assert_called_once()

    def test_discovers_the_sydney_stack_with_temporary_credentials(self):
        responses = [
            {"accountPlanType": "FREE", "accountPlanStatus": "ACTIVE"},
            {"Stacks": [{"StackStatus": "CREATE_COMPLETE",
                         "Outputs": [{"OutputKey": "BaseUrl", "OutputValue": URL}]}]},
            CREDENTIALS,
        ]
        with patch.dict(os.environ, {"GOD_AWS_STACK": "test-stack"}), patch(
            "aws_gateway.cli", side_effect=responses
        ) as aws:
            gateway = AwsGateway.discover("sample")
        self.assertEqual(gateway.host, "test123.execute-api.ap-southeast-2.amazonaws.com")
        self.assertEqual(aws.call_args_list[1].args, (
            "sample", "ap-southeast-2", "cloudformation", "describe-stacks", "--stack-name", "test-stack",
        ))
        self.assertEqual(gateway.model, "private-coder")

    def test_signing_binds_the_body_route_and_session(self):
        gateway = AwsGateway(URL, CREDENTIALS)
        stamp = datetime(2026, 11, 20, 0, 0, tzinfo=timezone.utc)
        one = sign_headers(gateway.host, gateway.path, b"first", CREDENTIALS, stamp)
        two = sign_headers(gateway.host, gateway.path, b"second", CREDENTIALS, stamp)
        self.assertIn("20261120/ap-southeast-2/execute-api/aws4_request", one["authorization"])
        self.assertEqual(one["x-amz-security-token"], "TOKEN")
        self.assertNotEqual(one["authorization"], two["authorization"])
        self.assertNotIn("FAKESECRET", json.dumps(one))

    def test_conversation_keeps_assistant_calls_and_tool_results_together(self):
        request = chat_request({"model": "client-supplied", "input": [
            {"role": "developer", "content": "approved rules"},
            {"type": "function_call", "call_id": "a", "name": "status", "arguments": "{}"},
            {"type": "function_call", "call_id": "b", "name": "status", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "a", "output": "first"},
            {"type": "function_call_output", "call_id": "b", "output": "second"},
        ]}, "private-coder")
        self.assertEqual(request["model"], "private-coder")
        self.assertEqual([message["role"] for message in request["messages"]], ["system", "assistant", "tool", "tool"])
        self.assertEqual([call["id"] for call in request["messages"][1]["tool_calls"]], ["a", "b"])

    def test_truncated_stream_does_not_release_a_tool_call(self):
        content = data_event({"tool_calls": [{"index": 0, "id": "a", "function": {"name": "status", "arguments": "{}"}}]})
        response = b"".join(response_events(io.BytesIO(content), "private-coder"))
        self.assertIn(b"response.failed", response)
        self.assertNotIn(b"response.output_item.done", response)

    def test_complete_stream_emits_the_function_only_after_arguments_validate(self):
        content = data_event({"tool_calls": [{"index": 0, "id": "a", "function": {"name": "status", "arguments": '{"x":'}}]})
        content += data_event({"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]}, "tool_calls")
        response = b"".join(response_events(io.BytesIO(content + DONE), "private-coder"))
        events = [json.loads(line[6:]) for line in response.splitlines() if line.startswith(b"data: ")]
        self.assertEqual(events[-1]["type"], "response.completed")
        self.assertEqual(events[-1]["response"]["output"][0]["arguments"], '{"x":1}')


@unittest.skipUnless(os.getenv("GOD_DOCKER_TEST") == "1", "requires WSL and the worker image")
class CodexChatBridge(unittest.TestCase):
    def test_codex_edits_and_verifies_a_file_through_mock_aws(self):
        requests = []
        signatures = []

        class MockGateway(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append(body)
                signatures.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("X-Limpid-Route", "free-auto")
                self.end_headers()
                if len(requests) == 1:
                    tool = next(tool["function"]["name"] for tool in body["tools"]
                                if tool["function"]["name"] in ("exec_command", "shell_command"))
                    key = "cmd" if tool == "exec_command" else "command"
                    command = 'echo verified > result.txt && test "$(cat result.txt)" = verified && echo sam@example.com'
                    args = json.dumps({key: command})
                    self.wfile.write(data_event({
                        "tool_calls": [{"index": 0, "id": "call_local", "type": "function",
                                        "function": {"name": tool, "arguments": args[:20]}}],
                    }))
                    self.wfile.write(data_event({
                        "tool_calls": [{"index": 0, "function": {"arguments": args[20:]}}],
                    }, "tool_calls"))
                else:
                    self.wfile.write(data_event({"content": "Verified."}, "stop"))
                self.wfile.write(DONE)
                self.wfile.flush()

        api = ThreadingHTTPServer(("127.0.0.1", 0), MockGateway)
        threading.Thread(target=api.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
                local = Path(folder)
                repo = local / "repo"
                repo.mkdir()
                subprocess.run(["git", "init", "-q", repo], check=True)
                (repo / "initial").write_text("initial\n")
                subprocess.run(["git", "-C", repo, "add", "initial"], check=True)
                state = local / "state"
                args = Namespace(action="task", brief="test with sam@example.com", parallel=False,
                                 single=True, public_openrouter=True)
                def connection(host, timeout):
                    self.assertEqual(host, "test123.execute-api.ap-southeast-2.amazonaws.com")
                    return HTTPConnection(
                        "127.0.0.1", api.server_port, timeout=timeout)
                with patch.dict(os.environ, {"GOD_AWS_PROFILE": "sample"}), patch.object(
                    AwsGateway, "discover", return_value=AwsGateway(URL, CREDENTIALS, public=True)
                ) as discover, patch("aws_gateway.http.client.HTTPSConnection", side_effect=connection), patch.object(
                    run, "STATE", state
                ), patch.object(run, "CONFIG", local / "config"):
                    run.run(args, repo)
                discover.assert_called_once_with("sample", public=True)
                diff = next(state.glob("*/changes.patch"))
                self.assertIn(b"+verified", diff.read_bytes())
                subprocess.run(["git", "-C", repo, "apply", diff], check=True)
                self.assertEqual((repo / "result.txt").read_text(), "verified\n")
                self.assertEqual(len(requests), 2)
                self.assertTrue(all(request["model"] == "private-coder-public" for request in requests))
                self.assertTrue(all(signature and "/execute-api/aws4_request" in signature for signature in signatures))
                outputs = [message for message in requests[1]["messages"] if message["role"] == "tool"]
                self.assertEqual(outputs[0]["tool_call_id"], "call_local")
                self.assertIn("REDACTED_", outputs[0]["content"])
                self.assertNotIn("sam@example.com", json.dumps(requests))
        finally:
            api.shutdown()
            api.server_close()
