import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / "template/.claude/god/worker"))
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
                    tools = requests[0]["tools"]
                    names = [t.get("name") for t in tools]
                    # CLI versions may offer exec_command directly or inside a namespace.
                    name = next((n for n in names if n in ("exec_command", "shell_command")), "exec_command")
                    key = "cmd" if name == "exec_command" else "command"
                    item = {"type": "function_call", "id": "fc1", "call_id": "c1", "name": name,
                            "arguments": json.dumps({key: "echo verified > result.txt && echo sam@example.com"})}
                    if any(t.get("type") == "namespace" for t in tools):
                        item["namespace"] = "functions"
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
                from argparse import Namespace
                state = Path(tmp) / "state"
                with patch.object(run, "STATE", state), patch.object(run, "PORT", api.server_port):
                    run.run(Namespace(action="task", brief="test for sam@example.com", parallel=False, single=True), root)
                    diff = next(state.glob("*/changes.patch"))
                    self.assertIn(b"+verified", diff.read_bytes())
                    subprocess.run(["git", "-C", root, "apply", diff], check=True)
                    self.assertEqual((root / "result.txt").read_text(), "verified\n")
                self.assertGreaterEqual(len(requests), 2)
                self.assertTrue(any(t.get("name") in ("exec_command", "shell_command", "shell")
                                    for t in requests[0].get("tools", [])), "model must see an executable shell tool")
                self.assertNotIn("sam@example.com", json.dumps(requests))
        finally:
            api.shutdown()
            api.server_close()
