#!/usr/bin/env python3
"""Install or upgrade kit-owned files (.claude/skills, .claude/agents, .claude/god) without losing edits.

  kit_files.py install TEMPLATE_DIR REPO_DIR [--dry-run]
  kit_files.py shipped KIT_GIT_DIR > kit/shipped.sha256     regenerate the list of every version shipped

For each kit file, compared with the copy in the repo:
  missing                                   -> install
  identical                                 -> nothing to do
  unchanged since we installed it, or still
  byte-for-byte a version the kit shipped   -> upgrade
  anything else (you edited it)             -> keep yours, write the new version next to it as <file>.kit-new

"Installed" hashes live in .claude/god/manifest.json; "shipped" hashes in kit/shipped.sha256 (every version
of every kit file in this repo's git history, so upgrades from installs that predate the manifest work).
Prints one line per change, like the rest of install.sh: "  <action>  <path>".
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

KIT_DIRS = (".claude/skills", ".claude/agents", ".claude/god")
MANIFEST_REL = ".claude/god/manifest.json"
SKIP_PARTS = {"__pycache__"}
HERE = os.path.dirname(os.path.abspath(__file__))
SHIPPED = os.path.join(HERE, "shipped.sha256")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def kit_files(template):
    out = []
    for d in KIT_DIRS:
        base = os.path.join(template, d)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(x for x in dirnames if x not in SKIP_PARTS)
            for f in sorted(filenames):
                if f.endswith((".pyc", ".kit-new")):
                    continue
                full = os.path.join(dirpath, f)
                out.append((os.path.relpath(full, template).replace(os.sep, "/"), full))
    return out


def load_shipped(path=SHIPPED):
    """{rel: {sha256, ...}} from lines '<sha256>  <rel>'."""
    shipped = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                digest, rel = line.split(None, 1)
                shipped.setdefault(rel.strip(), set()).add(digest)
    except OSError:
        pass
    return shipped


def load_manifest(repo):
    try:
        with open(os.path.join(repo, MANIFEST_REL), encoding="utf-8") as fh:
            data = json.load(fh)
        return dict(data.get("files") or {})
    except (OSError, ValueError, AttributeError):
        return {}


def say(action, rel):
    print("  %-8s %s" % (action, rel))


def install(template, repo, dry_run=False):
    shipped = load_shipped()
    manifest = load_manifest(repo)
    new_manifest = dict(manifest)
    counts = {"install": 0, "upgrade": 0, "same": 0, "kept": 0}
    for rel, src in kit_files(template):
        dst = os.path.join(repo, rel)
        src_hash = sha256_file(src)
        if not os.path.exists(dst):
            action = "install"
        else:
            dst_hash = sha256_file(dst)
            if dst_hash == src_hash:
                new_manifest[rel] = src_hash
                counts["same"] += 1
                stale = dst + ".kit-new"
                if os.path.exists(stale) and not dry_run:
                    os.remove(stale)  # you merged it: the leftover suggestion is no longer needed
                continue
            if dst_hash == manifest.get(rel) or dst_hash in shipped.get(rel, ()):
                action = "upgrade"
            else:
                action = "kept"
        if action == "kept":
            say("keep", "%s (you edited it; new kit version saved as %s.kit-new — merge, then delete it)" % (rel, rel))
            if not dry_run:
                shutil.copy2(src, dst + ".kit-new")
        else:
            say(action, rel)
            if not dry_run:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
            new_manifest[rel] = src_hash
        counts[action] += 1
    if not dry_run:
        path = os.path.join(repo, MANIFEST_REL)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"_help": "Hashes of the kit files install.sh last installed here. A file that no longer "
                                "matches is yours: upgrades keep it and write <file>.kit-new instead.",
                       "files": dict(sorted(new_manifest.items()))}, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    print("  summary  %d installed, %d upgraded, %d unchanged, %d kept (edited by you)" % (
        counts["install"], counts["upgrade"], counts["same"], counts["kept"]))
    return 0


def shipped_from_git(kit_dir):
    """Every version of every kit-owned template file in git history, plus the working tree."""
    def git(*args):
        return subprocess.run(["git", "-C", kit_dir, *args], capture_output=True, check=True).stdout

    pairs = set()
    commits = git("rev-list", "HEAD", "--", "template/.claude").decode().split()
    for c in commits:
        for line in git("ls-tree", "-r", c, "--", *("template/" + d for d in KIT_DIRS)).decode().splitlines():
            meta, path = line.split("\t", 1)
            _, kind, blob = meta.split()
            if kind != "blob" or "__pycache__" in path:
                continue
            data = git("cat-file", "blob", blob)
            pairs.add((hashlib.sha256(data).hexdigest(), path[len("template/"):]))
    for rel, full in kit_files(os.path.join(kit_dir, "template")):
        pairs.add((sha256_file(full), rel))
    lines = ["# Every version of every kit-owned file the kit has shipped: '<sha256>  <path>'.",
             "# install.sh upgrades a file that still matches one of these; anything else counts as edited.",
             "# Regenerate with: python3 kit/kit_files.py shipped . > kit/shipped.sha256"]
    lines += ["%s  %s" % p for p in sorted(pairs, key=lambda p: (p[1], p[0]))]
    return "\n".join(lines) + "\n"


def main(argv):
    if len(argv) >= 3 and argv[0] == "install":
        return install(argv[1], argv[2], dry_run="--dry-run" in argv[3:])
    if len(argv) == 2 and argv[0] == "shipped":
        sys.stdout.write(shipped_from_git(argv[1]))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
