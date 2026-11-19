"""Send optional, metadata-only run notices from the WSL supervisor."""
import http.client
import json
import os
import re
import sys

SLACK_HOST = "hooks.slack.com"
WEBHOOK = re.compile(
    r"https://hooks\.slack\.com(?P<path>/services/[A-Za-z0-9]+/[A-Za-z0-9]+/[A-Za-z0-9_-]+)"
)


def slack_path(config):
    try:
        with (config / "slack-webhook").open() as secret:
            if os.fstat(secret.fileno()).st_mode & 0o077:
                raise ValueError("Slack webhook file must have owner-only permissions")
            value = secret.read(1025).strip()
    except FileNotFoundError:
        return None
    match = WEBHOOK.fullmatch(value)
    if len(value) > 1024 or match is None:
        raise ValueError("Slack webhook file must contain a Slack HTTPS incoming webhook URL")
    return match["path"]


def notify(config, action, outcome, run_id):
    """A notification failure leaves the recorded workflow outcome intact."""
    if (action not in {"task", "review"}
            or outcome not in {"completed", "failed"}
            or re.fullmatch(r"[a-f0-9]{12}", run_id) is None):
        return
    try:
        path = slack_path(config)
        if path is None:
            return
        payload = json.dumps({"text": f"God kit: {action} {outcome}. Run `{run_id}`."})
        connection = http.client.HTTPSConnection(SLACK_HOST, timeout=4)
        try:
            connection.request("POST", path, payload, {"Content-Type": "application/json"})
            with connection.getresponse() as response:
                if response.status != 200:
                    print(f"god: Slack notification rejected (HTTP {response.status}).", file=sys.stderr)
        finally:
            connection.close()
    except ValueError:
        print("god: Slack notification configuration is invalid. Run god doctor.", file=sys.stderr)
    except (OSError, http.client.HTTPException):
        print("god: Slack notification unavailable. Check the webhook and connection.", file=sys.stderr)
