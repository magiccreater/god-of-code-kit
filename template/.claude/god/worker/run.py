"""WSL supervisor. Each model worker sees a filtered snapshot and a per-run relay."""
import argparse
import configparser
from concurrent.futures import ThreadPoolExecutor
from fnmatch import fnmatch
import http.client
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid

from linux_workspace import require_linux_workspace
from relay import Sanitizer, Server

HERE = Path(__file__).resolve().parent
DEFAULT_IMAGE = "god-kit-worker:0.170.0"
IMAGE = os.getenv("GOD_WORKER_IMAGE", DEFAULT_IMAGE)
STATE = Path.home() / ".local/state/god-kit"
CONFIG = Path.home() / ".config/god-kit"
PORT = 18182
SKIP = {".git", ".codex", ".ssh", ".aws", ".oci", ".gnupg", ".venv", "node_modules",
        ".npmrc", ".netrc", ".pypirc", ".docker", "credentials", "id_rsa", "id_ed25519"}
PATTERNS = (".env*", "*.pem", "*.key", "*.p12", "*.pfx", "*.tfstate*", "*.kubeconfig")


def cmd(*args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def capture(*args, **kwargs):
    return cmd(*args, stdout=subprocess.PIPE, **kwargs).stdout


def lines(name):
    path = CONFIG / name
    return path.read_text().splitlines() if path.is_file() else []


def image_ready():
    return subprocess.run(["docker", "image", "inspect", IMAGE], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def health():
    connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
    try:
        connection.request("GET", "/health")
        return connection.getresponse().status == 200
    except OSError:
        return False
    finally:
        connection.close()


def doctor():
    profile = Path.home() / ".oci/config"
    print("OCI CLI:", shutil.which("oci") or "missing (uv tool install oci-cli --python 3.12)")
    print("OCI credentials:", "configured" if profile.exists() else "missing (god oracle auth)")
    if profile.exists() and shutil.which("oci"):
        try:
            config = configparser.ConfigParser(interpolation=None)
            config.read(profile)
            if not config["DEFAULT"].get("user", "").startswith("ocid1.user."):
                print("OCI profile: DEFAULT.user must be the user OCID from the key's configuration preview. "
                      "DEFAULT.tenancy takes the tenancy OCID.")
            probe = subprocess.run(["oci", "iam", "availability-domain", "list", "--query", "length(data)",
                                    "--raw-output", "--connection-timeout", "5", "--read-timeout", "8"],
                                   capture_output=True, timeout=16)
            if probe.returncode == 0:
                print("OCI authentication: verified")
            elif b"NotAuthenticated" in probe.stderr:
                print("OCI authentication: rejected. Upload the matching public PEM under your user's API Keys, then retry.")
            else:
                print("OCI authentication: check profile and IAM permissions with oci iam availability-domain list")
        except subprocess.TimeoutExpired:
            print("OCI authentication: timed out contacting OCI. Check networking and the configured region.")
        except configparser.Error:
            print("OCI profile: malformed INI. Compare ~/.oci/config with the key's configuration preview.")
    docker = shutil.which("docker") and subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL,
                                                        stderr=subprocess.DEVNULL).returncode == 0
    print("Docker:", "ready" if docker else "unavailable (start Docker inside WSL)")
    print("Worker:", "ready" if docker and image_ready() else "built automatically on the first task")
    ok = health()
    state = Path.home() / ".local/state/god-oracle"
    if ok:
        print("Inference: ready")
    elif not (state / "ip").is_file():
        print("VM: not provisioned by this profile (god oracle up after authentication)")
    else:
        probe = http.client.HTTPConnection("127.0.0.1", PORT, timeout=4)
        try:
            probe.request("GET", "/health")
            print("Tunnel: reachable. Model health HTTP", probe.getresponse().status, "(god oracle logs)")
        except OSError:
            print("Tunnel: disconnected (god oracle tunnel)")
        finally:
            probe.close()
    return 0 if ok and docker else 1


def snapshot(root, project):
    raw = capture("git", "-C", root, "ls-files", "-z")
    raw += capture("git", "-C", root, "diff", "--cached", "--diff-filter=D", "--name-only", "-z")
    names = {Path(os.fsdecode(x)) for x in raw.split(b"\0") if x}
    # Private-mode kit files are intentionally untracked. Include only its Markdown workflow.
    for folder in (".ai", ".claude/skills"):
        names.update(p.relative_to(root) for p in (root / folder).rglob("*.md"))
    excludes = [x for x in lines("exclude") if x and not x.startswith("#")]
    visible = []
    for rel in sorted(names):
        src = root / rel
        if (any(p in SKIP or any(fnmatch(p, pat) for pat in PATTERNS) for p in rel.parts)
                or rel.parts[:2] == (".ai", "review") or any(fnmatch(str(rel), pat) for pat in excludes)
                or src.resolve() != src):
            continue
        visible.append(str(rel))
        if not src.is_file():
            continue
        dest = project / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    return visible


def pending_diff(root, paths):
    exists = subprocess.run(["git", "-C", root, "rev-parse", "--verify", "HEAD"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    target = ["HEAD"] if exists else ["--cached"]
    chunks = []
    for start in range(0, len(paths), 80):
        chunks.append(capture("git", "-C", root, "--literal-pathspecs", "diff", "--no-ext-diff",
                              "--no-textconv", "--no-renames", *target, "--", *paths[start:start+80]))
    return b"".join(chunks)


def worker(project, socket_dir, prompt, review=False):
    with tempfile.TemporaryDirectory(dir=STATE) as out:
        args = ["docker", "run", "--rm", "--network", "none", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--pids-limit", "256", "--memory", "2g",
                "--cpus", "2", "--user", f"{os.getuid()}:{os.getgid()}", "--read-only",
                "--tmpfs", "/tmp:rw,nosuid,nodev,mode=1777", "-e", "HOME=/tmp/agent", "-w", "/project",
                "-v", f"{project}:/project:{'ro' if review else 'rw'}", "-v", f"{socket_dir}:/relay:ro",
                "-v", f"{out}:/result:rw", "-i", IMAGE, "sh", "-ec",
                'mkdir -p "$HOME"; python3 /opt/god/bridge.py & '
                'exec codex exec --ephemeral --skip-git-repo-check --ignore-user-config '
                '-c model_provider=\'"oci"\' -c model_providers.oci.name=\'"Oracle"\' '
                '-c model_providers.oci.base_url=\'"http://127.0.0.1:8183/v1"\' '
                '-c model_providers.oci.wire_api=\'"responses"\' '
                '-c model_providers.oci.supports_websockets=false -c model_providers.oci.request_max_retries=0 '
                '-c model_providers.oci.stream_max_retries=0 -c model_context_window=24576 '
                '-m oci-local --sandbox danger-full-access -o /result/message -']
        # The outer container enforces read-only review, offline execution and mount boundaries.
        cmd(*args, input=prompt.encode())
        return (Path(out) / "message").read_text()


def task_plan(project, brief):
    """Only independent, explicitly scoped units may run concurrently."""
    files = [str(p.relative_to(project)) for p in sorted(project.rglob("*"))
             if p.is_file() and not str(p.relative_to(project)).startswith(".")][:180]
    request = {"model": "oci-local", "max_output_tokens": 500, "stream": False,
               "instructions": "Plan this coding task. Return only JSON with an array named units. "
               "Use an empty array for a single worker. Only for two independent changes with a stable "
               "interface, return exactly two units, each with brief and files (exact relative paths, "
               "including tests). Shared files or dependencies require a single worker.",
               "input": json.dumps({"task": brief, "paths": files})}
    connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=150)
    try:
        cleaned = Sanitizer([v for v in lines("redact") if v]).clean(request)
        connection.request("POST", "/v1/responses", json.dumps(cleaned), {"Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            return []
        output = json.load(response)["output"]
        content = "".join(part["text"] for item in output for part in item.get("content", [])
                          if part.get("type") == "output_text").strip()
        units = json.loads(content)["units"]
        return validate_units(units)
    except (ValueError, OSError, KeyError, AttributeError, TypeError, http.client.HTTPException):
        return []
    finally:
        connection.close()


def validate_units(units):
    if not isinstance(units, list) or len(units) != 2:
        return []
    owned = set()
    for unit in units:
        if not isinstance(unit, dict) or not isinstance(unit.get("brief"), str):
            return []
        paths = unit.get("files")
        if not isinstance(paths, list) or not paths or len(paths) > 30:
            return []
        for name in paths:
            if not isinstance(name, str) or not name or name.startswith(("/", ".")) or ".." in Path(name).parts:
                return []
            if str(Path(name)) != name or name in owned:
                return []
            owned.add(name)
    return units


def baseline(project, metadata):
    git = ["git", "--git-dir=" + str(metadata), "--work-tree=" + str(project)]
    cmd(*git, "init", "-q")
    cmd(*git, "add", "-f", ".", cwd=project)
    return git, capture(*git, "write-tree").strip().decode()


def implement_units(project, socket_dir, units, brief):
    def implement(pair):
        index, unit = pair
        checkout = project.parent / ("unit-%s" % index)
        shutil.copytree(project, checkout)
        git, tree = baseline(checkout, project.parent / ("meta-%s" % index))
        result = worker(checkout, socket_dir, brief + "\nImplement only this unit, run its tests: " + json.dumps(unit))
        cmd(*git, "add", "-A", ".", cwd=checkout)
        names = capture(*git, "diff", "--cached", "--no-renames", "--name-only", "-z", tree).split(b"\0")
        if any(os.fsdecode(n) not in unit["files"] for n in names if n):
            raise ValueError("Workers crossed their file assignments.")
        return result, capture(*git, "diff", "--cached", "--binary", tree)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(implement, enumerate(units)))
    combined = b"".join(diff for _, diff in outputs)
    if combined:
        cmd("git", "apply", "--check", "-", cwd=project, input=combined)
        cmd("git", "apply", "-", cwd=project, input=combined)
    return "\n".join(report for report, _ in outputs)


def run(args, root):
    if not health():
        profile = Path(os.getenv("GOD_ORACLE_PROFILE", str(HERE.parents[4] /
                       "limpid-ai-dev-stack/dev-stack-template/oracle/profile"))) / "oracle.sh"
        if (Path.home() / ".local/state/god-oracle/ip").is_file() and profile.is_file():
            cmd("bash", profile, "tunnel")
        if not health():
            raise ValueError("Inference unavailable. Run god doctor for the next step.")
    if not image_ready():
        if IMAGE != DEFAULT_IMAGE:
            raise ValueError("Build the selected GOD_WORKER_IMAGE inside WSL first.")
        cmd("docker", "build", "-t", IMAGE, HERE)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:12]
    record = STATE / run_id
    record.mkdir(mode=0o700)
    (record / "repo").write_text(str(root))
    print("Run", run_id, flush=True)
    with tempfile.TemporaryDirectory(dir=STATE) as folder:
        base = Path(folder)
        project = base / "project"
        project.mkdir()
        visible = snapshot(root, project)
        git, tree = baseline(project, base / "baseline")
        relay_dir = base / "relay"
        relay_dir.mkdir()
        server = Server(relay_dir / "socket", PORT, [s for s in lines("redact") if s])
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            brief = "Read .ai/rules.md when present. Task: " + args.brief
            if args.action == "review":
                with tempfile.NamedTemporaryFile(prefix="pending-", suffix=".patch", dir=project) as pending:
                    pending.write(pending_diff(root, visible))
                    pending.flush()
                    result = worker(project, relay_dir, "Give a read-only second opinion with file references. "
                                    "The pending tracked diff is in " + Path(pending.name).name + ". " + brief, True)
            else:
                units = [] if args.single else task_plan(project, args.brief)
                (record / "plan.json").write_text(json.dumps(units, indent=2))
                if args.parallel or units:
                    roles = ["Research relevant implementation and dependencies.", "Design the change and its tests."]
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        notes = list(pool.map(lambda role: worker(project, relay_dir, role + "\n" + brief, True), roles))
                    brief += "\nResearch and design:\n" + "\n".join(notes)
                reports = ""
                if units:
                    print("Running two independent implementation units.", flush=True)
                    try:
                        reports = implement_units(project, relay_dir, units, brief)
                    except (ValueError, subprocess.CalledProcessError) as exc:
                        print("Continuing with a single integrator:", exc, file=sys.stderr)
                result = worker(project, relay_dir, brief + "\nImplement any missing work and run applicable tests on "
                                "the combined checkout. Report exact test results and blockers. "
                                "Dependencies must already be available offline. Do not commit.\n" + reports)
            (record / "report.txt").write_text(result)
            print(result)
            if args.action == "task":
                cmd(*git, "add", "-A", ".", cwd=project)
                patch = capture(*git, "diff", "--cached", "--binary", tree, cwd=project)
                (record / "changes.patch").write_bytes(patch)
                print("Apply with: god apply", run_id) if patch else print("No changes produced.")
        except (ValueError, OSError, subprocess.CalledProcessError) as exc:
            (record / "error.txt").write_text(str(exc))
            raise
        finally:
            server.shutdown()
            server.server_close()


def main():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="action", required=True)
    subs.add_parser("doctor")
    subs.add_parser("status")
    for name in ("task", "review"):
        child = subs.add_parser(name)
        child.add_argument("brief")
        if name == "task":
            child.add_argument("--parallel", action="store_true", help="research and design concurrently before implementing")
            child.add_argument("--single", action="store_true", help="skip the planning call and use one coding worker")
    subs.add_parser("apply").add_argument("run")
    args = parser.parse_args()
    if "microsoft" not in Path("/proc/sys/kernel/osrelease").read_text().lower():
        raise ValueError("Open an Ubuntu WSL terminal and run this command there.")
    if args.action == "doctor":
        return doctor()
    if args.action == "status":
        runs = sorted(STATE.glob("*/repo"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
        for marker in runs:
            folder = marker.parent
            status = "reported" if (folder / "report.txt").exists() else "incomplete"
            if (folder / "error.txt").exists():
                status = "failed"
            print(folder.name, status, marker.read_text(), "details:", folder)
        if not runs:
            print("No runs recorded.")
        return 0
    root = Path(os.fsdecode(capture("git", "rev-parse", "--show-toplevel")).strip()).resolve()
    require_linux_workspace(root)
    if args.action == "apply":
        import re
        if not re.fullmatch("[a-f0-9]{12}", args.run):
            raise ValueError("Use the run ID printed by god task.")
        record = STATE / args.run
        if (record / "repo").read_text() != str(root):
            raise ValueError("Run god apply inside the original repository.")
        patch = record / "changes.patch"
        cmd("git", "-C", root, "apply", "--check", patch)
        cmd("git", "-C", root, "apply", patch)
    else:
        run(args, root)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print("god:", exc, file=sys.stderr)
        sys.exit(1)
