#!/usr/bin/env python3
"""Manage kit-owned blocks inside files that also hold project content.

  blocks.py upsert TARGET SOURCE [TAG]   put SOURCE's block (or all of SOURCE) into TARGET between
                                         markers, replacing an existing block or appending one.
  blocks.py extract SOURCE [TAG]         print the block body from SOURCE.

Markers: <!-- god-of-code[:TAG]:begin --> ... <!-- god-of-code[:TAG]:end -->
Prints one of: add | update | keep  (what happened to TARGET).
"""
import os
import re
import sys


def markers(tag):
    t = f"god-of-code:{tag}" if tag else "god-of-code"
    return f"<!-- {t}:begin -->", f"<!-- {t}:end -->"


def extract(text, tag):
    b, e = markers(tag)
    m = re.search(re.escape(b) + r"\n?(.*?)\n?" + re.escape(e), text, re.S)
    return m.group(1) if m else None


def upsert(target, source, tag):
    with open(source, encoding="utf-8") as f:
        src = f.read()
    body = extract(src, tag)
    if body is None:
        body = src.strip("\n")
    b, e = markers(tag)
    block = f"{b}\n{body}\n{e}"
    if not os.path.exists(target):
        with open(target, "w", encoding="utf-8") as f:
            f.write(src if extract(src, tag) is not None else block + "\n")
        return "add"
    with open(target, encoding="utf-8") as f:
        cur = f.read()
    if extract(cur, tag) is not None:
        new = re.sub(re.escape(b) + r"\n?.*?\n?" + re.escape(e), lambda _m: block, cur, count=1, flags=re.S)
    else:
        new = cur.rstrip("\n") + ("\n\n" if cur.strip() else "") + block + "\n"
    if new == cur:
        return "keep"
    with open(target, "w", encoding="utf-8") as f:
        f.write(new)
    return "update"


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "upsert":
        print(upsert(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else ""))
    elif cmd == "extract":
        with open(sys.argv[2], encoding="utf-8") as f:
            body = extract(f.read(), sys.argv[3] if len(sys.argv) > 3 else "")
        print(body if body is not None else "")
    else:
        sys.exit(__doc__)
