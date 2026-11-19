from argparse import Namespace
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / "template/.claude/god/worker"))
import agent
import notifications
import relay
import run


class Redaction(unittest.TestCase):
    def test_independent_scope(self):
        units = [{"brief": "add api", "files": ["api.py"]}, {"brief": "update ui", "files": ["app.ts"]}]
        self.assertEqual(run.validate_units(units), units)
        for unsafe in ("api.py", "../outside", ".git/config", "/tmp/test", "nested/../test"):
            self.assertEqual(run.validate_units([units[0], {"brief": "b", "files": [unsafe]}]), [])

    def test_parallel_changes_integrate(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            def implement(checkout, _, prompt):
                unit = json.loads(prompt.split("run its tests: ")[1])
                (checkout / unit["files"][0]).write_text(unit["brief"])
                return "done"
            units = [{"brief": "a", "files": ["a.txt"]}, {"brief": "b", "files": ["b.txt"]}]
            with patch.object(run, "worker", implement):
                run.implement_units(project, Path(tmp), units, "test")
            self.assertEqual(sorted(p.name for p in project.iterdir()), ["a.txt", "b.txt"])

    def test_all_turns(self):
        sanitizer = relay.Sanitizer(["customer-eleven"])
        body = {"input": [{"role": "user", "content": "customer-eleven sam@example.com"},
                          {"type": "function_call_output", "output": '{"password":"sensitive123"}'}]}
        clean = json.dumps(sanitizer.clean(body))
        for value in ("customer-eleven", "sam@example.com", "sensitive123"):
            self.assertNotIn(value, clean)

    def test_fail_closed(self):
        for value in ({"type": "input_image"}, "-----BEGIN PRIVATE KEY-----"):
            with self.assertRaises(ValueError):
                relay.Sanitizer().clean(value)


class SlackNotifications(unittest.TestCase):
    def test_success_sends_only_run_metadata(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            hook = root / "slack-webhook"
            hook.write_text("https://hooks.slack.com/services/T123/B456/local-secret\n")
            hook.chmod(0o600)
            with patch.object(notifications.http.client, "HTTPSConnection") as network:
                connection = network.return_value
                connection.getresponse.return_value.__enter__.return_value.status = 200
                notifications.notify(root, "task", "completed", "0123456789ab")
                network.assert_called_once_with("hooks.slack.com", timeout=4)
                method, path, payload, headers = connection.request.call_args[0]
                self.assertEqual(method, "POST")
                self.assertEqual(path, "/services/T123/B456/local-secret")
                self.assertEqual(json.loads(payload), {"text": "God kit: task completed. Run `0123456789ab`."})
                self.assertEqual(headers, {"Content-Type": "application/json"})
                connection.close.assert_called_once()

    def test_missing_insecure_and_non_slack_config_never_sends(self):
        with tempfile.TemporaryDirectory() as scratch, patch.object(
            notifications.http.client, "HTTPSConnection"
        ) as network, patch.object(notifications.sys, "stderr"):
            root = Path(scratch)
            notifications.notify(root, "task", "failed", "0123456789ab")
            hook = root / "slack-webhook"
            hook.write_text("https://hooks.slack.com/services/T123/B456/local-secret\n")
            hook.chmod(0o644)
            notifications.notify(root, "task", "failed", "0123456789ab")
            hook.chmod(0o600)
            hook.write_text("https://hooks.slack.com@example.net/services/T123/B456/local-secret\n")
            notifications.notify(root, "task", "failed", "0123456789ab")
            network.assert_not_called()

    def test_task_failure_is_recorded_before_notification(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            args = Namespace(action="task")

            def notice(config, action, outcome, run_id):
                self.assertEqual(action, "task")
                self.assertEqual(outcome, "failed")
                self.assertEqual((root / run_id / "error.txt").read_text(), "model unavailable")

            with patch.object(run, "STATE", root), patch.object(
                run, "execute", side_effect=ValueError("model unavailable")
            ), patch.object(run, "notify", side_effect=notice) as send:
                with self.assertRaisesRegex(ValueError, "model unavailable"):
                    run.run(args, root)
                send.assert_called_once()


class NativeWorker(unittest.TestCase):
    def test_incomplete_response_cannot_run_a_command(self):
        connection = MagicMock()
        response = connection.getresponse.return_value.__enter__.return_value
        response.status = 200
        response.getheader.return_value = "text/event-stream"
        item = {"type": "response.output_item.done", "item": {"type": "function_call",
                "call_id": "1", "name": "exec_command", "arguments": '{"cmd":"true"}'}}
        response.readline.side_effect = io.BytesIO(
            ("data: " + json.dumps(item) + "\n\n").encode()
        ).readline
        with patch.object(agent, "RelayConnection", return_value=connection), patch.object(
            agent, "execute_command",
        ) as execute:
            with self.assertRaisesRegex(ValueError, "without a complete response"):
                agent.run("Example task", "sample")
            execute.assert_not_called()

    def test_command_returns_exit_code_and_bounds_output(self):
        with patch.object(agent, "MAX_OUTPUT", 4):
            output = agent.execute_command("printf 123456; exit 3")
        self.assertEqual(output, "Exit code: 3\n1234\n[Output truncated]")

    def test_command_timeout_terminates_background_processes(self):
        with patch.object(agent, "COMMAND_TIMEOUT", 0.1):
            output = agent.execute_command("sleep 30 & wait")
        self.assertIn("Command timed out", output)

    def test_explicit_permission_request_is_never_executed(self):
        with patch.object(agent, "execute_command") as execute:
            result = agent.tool_result({"name": "exec_command", "arguments": json.dumps({
                "cmd": "true", "sandbox_permissions": "require_escalated",
            })})
        self.assertIn("Invalid arguments", result)
        execute.assert_not_called()


@unittest.skipUnless(os.getenv("GOD_DOCKER_TEST") == "1", "requires WSL and the worker image")
class EndToEnd(unittest.TestCase):
    def test_cli_two_turns_and_patch(self):
        requests = []

        class Fake(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.end_headers()

            def do_POST(self):
                data = self.rfile.read(int(self.headers["Content-Length"]))
                requests.append(json.loads(data))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                def emit(kind, **fields):
                    event = {"type": kind, **fields}
                    self.wfile.write(("event: " + kind + "\ndata: " + json.dumps(event) + "\n\n").encode())
                emit("response.created", response={"id": "r"+str(len(requests)), "object": "response"})
                if len(requests) == 1:
                    item = {"type": "function_call", "id": "fc1", "call_id": "c1", "name": "exec_command",
                            "arguments": json.dumps({"cmd": "echo verified > result.txt && echo sam@example.com"})}
                else:
                    item = {"type": "message", "id": "m1", "role": "assistant",
                            "content": [{"type": "output_text", "text": "Verified."}]}
                emit("response.output_item.added", output_index=0, item=item)
                emit("response.output_item.done", output_index=0, item=item)
                emit("response.completed", response={"id": "r"+str(len(requests)), "status": "completed",
                     "output": [item], "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20}})

        api = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=api.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
                root = Path(tmp) / "repo"
                root.mkdir()
                subprocess.run(["git", "init", "-q", root], check=True)
                (root / "one").write_text("baseline\n")
                subprocess.run(["git", "-C", root, "add", "one"], check=True)
                subprocess.run(["bash", KIT / "install.sh", root, "--private"], check=True, stdout=subprocess.DEVNULL)
                state = Path(tmp) / "state"
                with patch.dict(os.environ, {"GOD_AWS_PROFILE": ""}), patch.object(
                    run, "STATE", state
                ), patch.object(run, "PORT", api.server_port), patch.object(run, "CONFIG", Path(tmp) / "config"):
                    run.run(Namespace(action="task", brief="test for sam@example.com", parallel=False, single=True), root)
                    diff = next(state.glob("*/changes.patch"))
                    self.assertIn(b"+verified", diff.read_bytes())
                    subprocess.run(["git", "-C", root, "apply", diff], check=True)
                    self.assertEqual((root / "result.txt").read_text(), "verified\n")
                self.assertGreaterEqual(len(requests), 2)
                self.assertEqual([t["name"] for t in requests[0]["tools"]], ["exec_command"])
                self.assertNotIn("sam@example.com", json.dumps(requests))
        finally:
            api.shutdown()
            api.server_close()
