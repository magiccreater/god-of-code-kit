#!/usr/bin/env python3
"""Merge the kit's settings fragment into a Claude Code settings file without losing existing settings.

- Existing keys win (e.g. an existing "model" is kept).
- permissions.allow / permissions.deny are unioned.
- Hook entries are added only if a hook with the same script path is not already present.
Usage: merge_settings.py FRAGMENT TARGET
"""
import json
import os
import sys


def hook_scripts(entry):
    out = set()
    for h in entry.get("hooks", []):
        out.add(" ".join([h.get("command", "")] + list(h.get("args", []))))
    return out


def main(fragment_path, target_path):
    with open(fragment_path, encoding="utf-8") as f:
        frag = json.load(f)
    cur = {}
    if os.path.exists(target_path):
        with open(target_path, encoding="utf-8") as f:
            text = f.read().strip()
        cur = json.loads(text) if text else {}

    if "model" not in cur and "model" in frag:
        cur["model"] = frag["model"]

    perms = cur.setdefault("permissions", {})
    for key in ("allow", "deny"):
        merged = list(perms.get(key, []))
        for rule in frag.get("permissions", {}).get(key, []):
            if rule not in merged:
                merged.append(rule)
        if merged:
            perms[key] = merged

    hooks = cur.setdefault("hooks", {})
    for event, entries in frag.get("hooks", {}).items():
        existing = hooks.setdefault(event, [])
        have = set()
        for e in existing:
            have |= hook_scripts(e)
        for e in entries:
            if not (hook_scripts(e) & have):
                existing.append(e)

    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
