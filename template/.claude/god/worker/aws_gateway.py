"""Sign requests to the Sydney stack endpoint using temporary WSL AWS credentials."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import http.client
import json
import os
import re
import subprocess

from chat_responses import chat_request, complete_response, response_events

REGION = "ap-southeast-2"
ENDPOINT = re.compile(r"https://([a-z0-9]+\.execute-api\.ap-southeast-2\.amazonaws\.com)/pilot/v1")
DEFAULT_STACK = "limpid-chat-gateway"
MAX_REQUEST = 65536
MAX_RESPONSE = 2_000_000


class GatewayError(ValueError):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def cli(profile, region, *args):
    env = dict(os.environ, AWS_PAGER="", AWS_CLI_AUTO_PROMPT="off", AWS_MAX_ATTEMPTS="1",
               AWS_EC2_METADATA_DISABLED="true", AWS_IGNORE_CONFIGURED_ENDPOINT_URLS="true")
    try:
        result = subprocess.run(
            ["aws", "--profile", profile, "--region", region, "--output", "json",
             "--cli-connect-timeout", "4", "--cli-read-timeout", "8", *args],
            capture_output=True, text=True, timeout=18, env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GatewayError("WSL AWS CLI is unavailable. Check aws login and your network.") from exc
    if result.returncode:
        raise GatewayError(
            f"AWS {' '.join(args[:2])} failed. Check your WSL AWS profile, permissions, and stack.")
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise GatewayError("AWS CLI returned an invalid response.") from exc


def sign_headers(host, path, data, credentials, now):
    date = now.strftime("%Y%m%d")
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    payload_hash = hashlib.sha256(data).hexdigest()
    headers = {
        "content-type": "application/json",
        "host": host,
        "x-amz-date": stamp,
        "x-amz-security-token": credentials["SessionToken"],
    }
    names = ";".join(sorted(headers))
    canonical = "".join(f"{key}:{headers[key]}\n" for key in sorted(headers))
    request = "\n".join(("POST", path, "", canonical, names, payload_hash))
    scope = f"{date}/{REGION}/execute-api/aws4_request"
    message = "\n".join(("AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(request.encode()).hexdigest()))
    key = ("AWS4" + credentials["SecretAccessKey"]).encode()
    for part in (date, REGION, "execute-api", "aws4_request"):
        key = hmac.digest(key, part.encode(), "sha256")
    signature = hmac.new(key, message.encode(), "sha256").hexdigest()
    headers["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={credentials['AccessKeyId']}/{scope}, "
        f"SignedHeaders={names}, Signature={signature}"
    )
    return headers


class AwsGateway:
    def __init__(self, url, credentials, public=False, public_free=False):
        endpoint = ENDPOINT.fullmatch(url)
        if not endpoint:
            raise GatewayError("Expected the Sydney gateway stack's pilot BaseUrl.")
        if not all(isinstance(credentials.get(key), str) and credentials[key] for key in (
            "AccessKeyId", "SecretAccessKey", "SessionToken"
        )):
            raise GatewayError("The gateway requires temporary AWS login credentials.")
        self.host = endpoint[1]
        self.path = "/pilot/v1/chat/completions"
        self.credentials = credentials
        if public and public_free:
            raise GatewayError("Choose one public inference option.")
        self.model = "public-free-coder" if public_free else (
            "private-coder-public" if public else "private-coder"
        )

    @classmethod
    def discover(cls, profile, public=False, public_free=False):
        plan = cli(profile, "us-east-1", "freetier", "get-account-plan-state")
        if plan.get("accountPlanType") != "FREE" or plan.get("accountPlanStatus") != "ACTIVE":
            raise GatewayError("This WSL gateway requires an active AWS Free Plan.")
        stack_name = os.getenv("GOD_AWS_STACK", DEFAULT_STACK)
        if public_free and stack_name == DEFAULT_STACK:
            raise GatewayError("Set GOD_AWS_STACK=limpid-litellm-router for --public-free.")
        stack = cli(profile, REGION, "cloudformation", "describe-stacks", "--stack-name", stack_name)
        stacks = stack.get("Stacks") or []
        if len(stacks) != 1 or stacks[0].get("StackStatus") not in (
            "CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"
        ):
            raise GatewayError("The Sydney gateway stack is not ready.")
        outputs = stacks[0].get("Outputs", [])
        url = next((entry["OutputValue"] for entry in outputs if entry["OutputKey"] == "BaseUrl"), "")
        creds = cli(profile, REGION, "configure", "export-credentials", "--format", "process")
        return cls(url, creds, public=public, public_free=public_free)

    @contextmanager
    def open(self, body):
        try:
            request = chat_request(body, self.model)
        except (AttributeError, TypeError, ValueError, KeyError) as exc:
            raise GatewayError("Unsupported content for the AWS coding route.", 422) from exc
        data = json.dumps(request, separators=(",", ":"), ensure_ascii=False).encode()
        if len(data) > MAX_REQUEST:
            raise GatewayError("Request exceeds the AWS gateway's 64 KiB limit.", 413)
        headers = sign_headers(self.host, self.path, data, self.credentials, datetime.now(timezone.utc))
        connection = http.client.HTTPSConnection(self.host, timeout=30)
        try:
            connection.request("POST", self.path, data, headers)
            response = connection.getresponse()
            if response.status != 200:
                messages = {
                    400: "AWS gateway rejected the request.",
                    401: "AWS gateway authentication failed.",
                    403: "AWS gateway access denied.",
                    429: "AWS gateway or inference provider reached its quota.",
                    503: "AWS inference route is unavailable.",
                }
                raise GatewayError(messages.get(response.status, "AWS gateway request failed."),
                                   response.status if response.status in messages else 502)
            expected = "text/event-stream" if request["stream"] else "application/json"
            if not response.getheader("Content-Type", "").lower().startswith(expected):
                raise GatewayError("AWS gateway returned an unexpected response format.")
            yield response
        finally:
            connection.close()

    def complete(self, body):
        with self.open(body) as response:
            data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE:
                raise GatewayError("AWS gateway response exceeds the local limit.")
            return complete_response(json.loads(data), self.model)

    def events(self, response):
        return response_events(response, self.model)
