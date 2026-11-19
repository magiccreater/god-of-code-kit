"""One WSL Unix socket per run. Only sanitized Responses requests can cross it."""
import hashlib
import hmac
import http.client
import json
import re
import secrets
import socketserver
from http.server import BaseHTTPRequestHandler

from aws_gateway import GatewayError
from chat_responses import SHELL_TOOLS

PATTERNS = [
    re.compile(r"(?i)\bBearer[ \t]+[A-Za-z0-9._~+/=-]{6,}"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\b(?:gh[pousr]_|github_pat_|sk-|xox[baprs]-)[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    re.compile(r"(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)\b[\"']?\s*[:=]\s*[\"']?[^\s,;\"'}]{3,}"),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s\"']+"),
]
BLOCK = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|data:[^,]{0,100};base64,|(?:[A-Za-z0-9+/]{128,}={0,2})")
SECRET_FIELD = re.compile(r"(?i)^(password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret|authorization|cookie)$")
DISALLOWED_TYPES = {"input_image", "input_file", "computer_screenshot", "image_url", "item_reference",
                    "compaction", "web_search", "web_search_preview", "file_search", "mcp", "code_interpreter"}


class Sanitizer:
    def __init__(self, literals=()):
        self.key = secrets.token_bytes(32)
        self.literals = sorted(literals, key=len, reverse=True)

    def tag(self, value):
        return "[REDACTED_" + hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()[:12] + "]"

    def clean(self, value):
        if isinstance(value, dict):
            kind = value.get("type")
            if (isinstance(kind, str) and kind in DISALLOWED_TYPES) or any(k in value for k in (
                    "encrypted_content", "file_id", "image_url", "file_url", "previous_response_id")):
                raise ValueError("attachment or opaque history")
            return {self.clean(k): self.tag(str(v)) if SECRET_FIELD.fullmatch(k) else self.clean(v)
                    for k, v in value.items()}
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        if isinstance(value, str):
            if BLOCK.search(value):
                raise ValueError("key material or opaque content")
            # Tool arguments and command output can themselves be JSON-encoded strings.
            if value.lstrip().startswith(("{", "[")):
                try:
                    embedded = json.loads(value)
                except ValueError:
                    pass
                else:
                    if isinstance(embedded, (dict, list)):
                        return json.dumps(self.clean(embedded), ensure_ascii=False)
            for literal in self.literals:
                value = value.replace(literal, self.tag(literal))
            for pattern in PATTERNS:
                value = pattern.sub(lambda match: self.tag(match.group()), value)
        return value


class Relay(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.path != "/v1/responses":
            return self.send_error(404)
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 2_000_000:
                return self.send_error(413)
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError()
            if "tools" in body:
                if not isinstance(body["tools"], list) or not all(isinstance(tool, dict) for tool in body["tools"]):
                    raise ValueError("invalid tools")
                enabled = SHELL_TOOLS | {"write_stdin"}
                body["tools"] = [tool for tool in body["tools"] if tool.get("type") == "function"
                                 and tool.get("name") in enabled]
            # Forward only fields required for stateless text/tool turns.
            if body.get("previous_response_id"):
                raise ValueError("opaque history")
            body = {k: v for k, v in body.items() if k in {
                "input", "instructions", "tools", "model", "stream", "max_output_tokens", "text"}}
            cleaned = self.server.sanitizer.clean(body)
        except (ValueError, TypeError, RecursionError):
            return self.send_error(422, "WSL blocked unsupported content or key material")
        if self.server.aws_gateway:
            return self.relay_aws(cleaned)
        data = json.dumps(cleaned).encode()
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=300)
        try:
            headers = {"Content-Type": "application/json"}
            connection.request("POST", self.path, data, headers)
            response = connection.getresponse()
            self.send_response(response.status)
            self.send_header("Content-Type", response.getheader("Content-Type", "application/json"))
            self.end_headers()
            while chunk := response.read1(16384):
                self.wfile.write(chunk)
                self.wfile.flush()
        except (OSError, http.client.HTTPException):
            self.log_error("tunnel interrupted")
        finally:
            connection.close()


    def relay_aws(self, body):
        gateway = self.server.aws_gateway
        started = False
        try:
            if not body.get("stream"):
                data = json.dumps(gateway.complete(body)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                started = True
                self.wfile.write(data)
                return
            with gateway.open(body) as response:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                route = response.getheader("X-Limpid-Route")
                if route in ("bedrock", "free-auto"):
                    self.send_header("X-Limpid-Route", route)
                self.end_headers()
                started = True
                for event in gateway.events(response):
                    self.wfile.write(event)
                    self.wfile.flush()
        except GatewayError as error:
            if not started:
                self.send_error(error.status, str(error))
        except (AttributeError, KeyError, OSError, TypeError, ValueError, http.client.HTTPException):
            if not started:
                self.send_error(502, "AWS gateway response was unavailable")


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, path, port, literals=(), aws_gateway=None):
        self.aws_gateway = aws_gateway
        self.port = port
        self.sanitizer = Sanitizer(literals)
        super().__init__(str(path), Relay)
