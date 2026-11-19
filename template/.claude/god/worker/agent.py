"""Run model-requested coding commands inside the kit's offline container."""

import http.client
import json
import os
import selectors
import signal
import socket
import subprocess
import sys
import time

SOCKET = "/relay/socket"
MAX_TURNS = 12
MAX_REQUEST = 48 * 1024
MAX_STREAM = 2_000_000
MAX_OUTPUT = 4096
COMMAND_TIMEOUT = 300

INSTRUCTIONS = (
    "Work in the current project directory. Use exec_command to inspect relevant files, "
    "make requested changes when the assignment allows edits, and run applicable local tests. "
    "Follow applicable AGENTS.md files and .ai/rules.md when present. The sandbox has no network. "
    "Read focused excerpts to keep the tool output small. "
    "Give a concise final report with changes, tests actually run, and any blockers."
)
TOOL = {
    "type": "function",
    "name": "exec_command",
    "description": "Run a Bash command inside the offline project sandbox. Returns its exit code and combined output.",
    "parameters": {
        "type": "object",
        "properties": {"cmd": {"type": "string", "description": "Bash command to run from the project directory."}},
        "required": ["cmd"],
        "additionalProperties": False,
    },
}


class RelayConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(SOCKET)


def model_turn(payload, connection):
    connection.request("POST", "/v1/responses", payload, {"Content-Type": "application/json"})
    with connection.getresponse() as response:
        if response.status != 200:
            raise ValueError(f"Inference relay returned HTTP {response.status}: {response.reason}")
        if not response.getheader("Content-Type", "").lower().startswith("text/event-stream"):
            raise ValueError("Inference relay did not return a stream.")
        remaining = MAX_STREAM
        while remaining > 0:
            line = response.readline(remaining + 1)
            if not line:
                break
            remaining -= len(line)
            if remaining < 0:
                break
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                break
            event = json.loads(data)
            kind = event.get("type")
            if kind == "response.completed":
                result = event["response"]
                if result.get("status") == "completed" and isinstance(result.get("output"), list):
                    return result["output"]
                break
            if kind in ("response.failed", "response.incomplete", "error"):
                break
    raise ValueError("Inference stream ended without a complete response.")


def stop_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def execute_command(command):
    deadline = time.monotonic() + COMMAND_TIMEOUT
    output = bytearray()
    truncated = False
    with subprocess.Popen(
        ["/bin/bash", "-c", command], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, start_new_session=True,
    ) as process, selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while True:
                if not selector.select(max(0, deadline - time.monotonic())) or time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(command, COMMAND_TIMEOUT)
                chunk = os.read(process.stdout.fileno(), 8192)
                if not chunk:
                    break
                available = MAX_OUTPUT - len(output)
                truncated = truncated or len(chunk) > available
                output.extend(chunk[:available])
            status = f"Exit code: {process.wait(timeout=max(0, deadline - time.monotonic()))}"
        except subprocess.TimeoutExpired:
            status = f"Command timed out after {COMMAND_TIMEOUT} seconds"
        finally:
            stop_group(process)
    text = output.decode(errors="replace")
    return f"{status}\n{text}" + ("\n[Output truncated]" if truncated else "")


def tool_result(call):
    if call["name"] != TOOL["name"]:
        return "Unknown tool. Use exec_command."
    try:
        arguments = json.loads(call["arguments"])
    except ValueError:
        return "Invalid arguments. Supply a JSON object containing only cmd."
    if (not isinstance(arguments, dict) or set(arguments) != {"cmd"}
            or not isinstance(arguments["cmd"], str) or not arguments["cmd"].strip()
            or "\0" in arguments["cmd"] or len(arguments["cmd"].encode()) > 8192):
        return "Invalid arguments. Supply one Bash command in cmd (up to 8192 bytes)."
    return execute_command(arguments["cmd"])


def run(prompt, model):
    initial = {"role": "user", "content": prompt}
    exchanges = []
    for _ in range(MAX_TURNS):
        # Drop complete old exchanges together so every tool output keeps its matching call.
        while True:
            request = {"model": model, "instructions": INSTRUCTIONS, "stream": True,
                       "max_output_tokens": 2048, "tools": [TOOL],
                       "input": [initial] + [item for exchange in exchanges for item in exchange]}
            payload = json.dumps(request, ensure_ascii=False).encode()
            if len(payload) <= MAX_REQUEST:
                break
            if len(exchanges) <= 1:
                raise ValueError("Task context is too large. Narrow the task or request shorter excerpts.")
            exchanges.pop(0)

        connection = RelayConnection("localhost", timeout=310)
        try:
            output = model_turn(payload, connection)
        finally:
            connection.close()

        calls = []
        text = []
        for item in output:
            if item["type"] == "function_call":
                calls.append({key: item[key] for key in ("type", "call_id", "name", "arguments")})
            elif item["type"] == "message":
                text.extend(part["text"] for part in item["content"] if part["type"] == "output_text")
        if not calls:
            if not text or not any(part.strip() for part in text):
                raise ValueError("Inference returned neither commands nor a final report.")
            return "\n".join(text)
        ids = [call["call_id"] for call in calls]
        if (len(calls) > 4 or not all(isinstance(item, str) and item for call in calls
                                     for key, item in call.items() if key != "type")
                or len(ids) != len(set(ids))):
            raise ValueError("Inference returned invalid commands or more than four commands in one turn.")
        results = [{"type": "function_call_output", "call_id": call["call_id"], "output": tool_result(call)}
                   for call in calls]
        exchanges.append(calls + results)
    raise ValueError(f"Worker reached its {MAX_TURNS}-turn limit. Try a smaller task.")


if __name__ == "__main__":
    try:
        print(run(sys.stdin.read(), sys.argv[1]))
    except (ValueError, OSError, KeyError, TypeError, AttributeError, http.client.HTTPException) as error:
        print(f"Worker: {error}", file=sys.stderr)
        sys.exit(1)
