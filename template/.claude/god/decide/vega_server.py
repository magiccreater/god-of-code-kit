#!/usr/bin/env python3
"""Serve vegaml (github.com/NandhaKishorM/vegaml, Apache-2.0) over the /v1/systemone wire protocol,
so the decision gate - or any Jev client - can call it like laya-serve or TypeSafe Jev.

  python vega_server.py setup [--size 0.8b|4b] [--revision REV]   download once, pin, verify
  python vega_server.py serve [--host 127.0.0.1] [--port 8765]     answer offline from the pinned copy

setup is the only step that touches the network. It downloads the checkpoint at an immutable
revision, loads it once (which also caches the Qwen backbone), and writes a manifest with the
SHA-256 of every checkpoint file. serve runs with Hugging Face in offline mode, re-hashes the files
against the manifest and refuses to start on any mismatch, so nothing is downloaded or swapped at
decision time. Re-run setup to move to a newer revision.

Needs: pip install vegaml   (torch + transformers; a GPU is optional but CPU is slow - measure it).
Binds to 127.0.0.1 by default. Set VEGA_SERVER_API_KEY to require "Authorization: Bearer <key>".
"""
import argparse
import hashlib
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_MANIFEST = os.path.join(os.path.expanduser("~"), ".cache", "god-of-code", "vega", "manifest.json")
TYPE_TO_VEGA = {"noul": "boolean", "boolean": "boolean", "choice": "choice", "score": "score"}
MAX_BODY = 2_000_000


# --------------------------------------------------------------------------- wire translation
def to_vega_question(q):
    """Jev/laya question -> vegaml question. Raises ValueError for unsupported types."""
    t = TYPE_TO_VEGA.get(q.get("type"))
    if t is None:
        raise ValueError("unsupported question type %r" % q.get("type"))
    if not q.get("instructions"):
        raise ValueError("instructions are required")
    out = {"type": t, "instructions": q["instructions"]}
    if q.get("criteria") is not None:
        out["criteria"] = q["criteria"]
    elif t != "boolean":
        raise ValueError("%s questions need criteria" % q["type"])
    return out


def from_vega_answer(wire_type, a):
    """vegaml engine answer -> Jev/laya-shaped answer, keeping vega's extra uncertainty fields."""
    probs = {str(k): float(v) for k, v in (a.get("probs") or {}).items()}
    conf = float(a.get("confidence", max(probs.values()) if probs else 0.0))
    extra = {"abstain": bool(a.get("abstain", False)), "unbound": bool(a.get("unbound", False))}
    if a.get("prediction_set") is not None:
        extra["prediction_set"] = [str(x).lower() if isinstance(x, bool) else str(x) for x in a["prediction_set"]]
    if wire_type in ("noul", "boolean"):
        p_yes = float(a["boolean"]) if "boolean" in a else float(probs.get("True", probs.get("true", 0.0)))
        out = {"type": "noul", "noul": round(p_yes, 6), "confidence": round(conf, 6),
               "answer_confidence": round(conf, 6),
               "probabilities": {"false": round(1.0 - p_yes, 6), "true": round(p_yes, 6)}}
    elif wire_type == "choice":
        out = {"type": "choice", "choice": a["choice"], "confidence": round(conf, 6),
               "answer_confidence": round(conf, 6), "probabilities": {k: round(v, 6) for k, v in probs.items()}}
    else:
        out = {"type": "score", "score": float(a.get("expected_score", a.get("score", 0))),
               "level": a.get("score"), "confidence": round(conf, 6), "answer_confidence": round(conf, 6),
               "probabilities": {k: round(v, 6) for k, v in probs.items()}}
    out.update(extra)
    return out


def handle_request(engine, model_name, body):
    """Validate a /v1/systemone body, run the engine, return the response object."""
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    state, questions = body.get("state"), body.get("questions")
    if state in (None, "", [], {}):
        raise ValueError("state is required")
    if not isinstance(questions, dict) or not questions:
        raise ValueError("questions must be a non-empty object")
    vq = {qid: to_vega_question(q) for qid, q in questions.items()}
    out = engine.decide(state, vq, mode="engine")
    answers = {qid: from_vega_answer(questions[qid]["type"], out["answers"][qid]) for qid in questions}
    return {"model": model_name, "answers": answers,
            "usage": {"input_tokens": int(out.get("n_tokens", 0)), "output_tokens": 0},
            "latency_ms": out.get("latency_ms")}


# --------------------------------------------------------------------------- setup / verification
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def checkpoint_files(path):
    out = {}
    for dirpath, _, files in os.walk(path):
        for f in files:
            if f.endswith((".safetensors", ".json")):
                full = os.path.join(dirpath, f)
                out[os.path.relpath(full, path).replace(os.sep, "/")] = sha256_file(full)
    return out


def cmd_setup(args):
    import vegaml  # noqa: imported here so `serve --help` and the tests work without it
    from huggingface_hub import HfApi
    from vegaml.hub import DEFAULT_REPO
    revision = args.revision
    if not revision:
        revision = HfApi().model_info(DEFAULT_REPO).sha
        print("Latest revision of %s: %s" % (DEFAULT_REPO, revision))
    path = vegaml.fetch(args.size, revision=revision)
    print("Loading once to cache the backbone (first run downloads it)...")
    t0 = time.time()
    v = vegaml.load(path, mode="engine")
    probe = v.decide("The tests pass and the change is small.",
                     {"ok": {"type": "boolean", "instructions": "Is this a good sign?"}}, mode="engine")
    print("Loaded in %.0fs; probe answer: %.3f" % (time.time() - t0, probe["answers"]["ok"]["boolean"]))
    manifest = {"size": args.size, "repo": DEFAULT_REPO, "revision": revision, "path": path,
                "backbone": (getattr(v.engine, "cfg", None) or {}).get("backbone_name"),
                "files": checkpoint_files(path),
                "vegaml_version": getattr(vegaml, "__version__", "?"),
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    os.makedirs(os.path.dirname(args.manifest), exist_ok=True)
    with open(args.manifest, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    print("Pinned %s@%s -> %s" % (args.size, revision[:12], args.manifest))
    return 0


def load_verified(manifest_path):
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    actual = checkpoint_files(manifest["path"])
    if actual != manifest["files"]:
        changed = sorted(set(actual.items()) ^ set(manifest["files"].items()))
        raise SystemExit("checkpoint files differ from %s (%s): re-run setup" % (manifest_path, changed[:3]))
    return manifest


def cmd_serve(args):
    if not os.path.exists(args.manifest):
        raise SystemExit("no manifest at %s: run `python vega_server.py setup` first" % args.manifest)
    os.environ["HF_HUB_OFFLINE"] = "1"         # no downloads at decision time
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    manifest = load_verified(args.manifest)
    import vegaml
    engine = vegaml.load(manifest["path"], mode="engine")
    model_name = "vega-%s@%s" % (manifest["size"], manifest["revision"][:12])
    api_key = os.environ.get("VEGA_SERVER_API_KEY", "")
    lock = threading.Lock()  # one decision at a time: the engine is not built for concurrent calls

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            data = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/health"):
                self._send(200, {"status": "ok", "model": model_name})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/v1/systemone":
                return self._send(404, {"error": "not found"})
            if api_key and self.headers.get("Authorization", "") != "Bearer " + api_key:
                return self._send(401, {"error": "missing or wrong API key"})
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                return self._send(413, {"error": "body missing or too large"})
            try:
                body = json.loads(self.rfile.read(length))
                with lock:
                    resp = handle_request(engine, model_name, body)
            except ValueError as exc:
                return self._send(422, {"error": str(exc)})
            except Exception as exc:  # never leak a traceback to the client
                sys.stderr.write("decision failed: %r\n" % exc)
                return self._send(500, {"error": "decision failed"})
            self._send(200, resp)

        def log_message(self, fmt, *a):
            sys.stderr.write("vega %s\n" % (fmt % a))

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("vega_server: %s on http://%s:%d/v1/systemone (offline, verified)" % (model_name, args.host, args.port))
    server.serve_forever()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("setup", help="download a pinned checkpoint and write the manifest")
    s.add_argument("--size", default="0.8b", choices=["0.8b", "4b"])
    s.add_argument("--revision", help="checkpoint revision (commit sha); default: latest, then pinned")
    s.add_argument("--manifest", default=DEFAULT_MANIFEST)
    v = sub.add_parser("serve", help="serve the pinned checkpoint offline")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8765)
    v.add_argument("--manifest", default=DEFAULT_MANIFEST)
    args = ap.parse_args(argv)
    if args.cmd == "setup":
        return cmd_setup(args)
    if args.cmd == "serve":
        return cmd_serve(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
