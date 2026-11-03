#!/usr/bin/env python3
"""Print directories matching a typed path, as a JSON list of absolute paths.

argv[1] is the text typed so far (~ is expanded). "~/pro" lists the folders in
~ whose names start with "pro"; "~/projects/" lists everything in ~/projects.
The typed path itself comes first when it is a directory. Hidden folders show
only when the typed name starts with ".".
"""
import json
import os
import sys

LIMIT = 20


def complete(text):
    path = os.path.expanduser(text)
    if not os.path.isabs(path):
        return []
    parent, prefix = os.path.split(path)
    out = []
    if prefix and os.path.isdir(path):
        out.append(path)
    try:
        entries = sorted(os.scandir(parent or "/"), key=lambda e: e.name.lower())
    except OSError:
        return out
    lowered = prefix.lower()
    for entry in entries:
        if len(out) >= LIMIT:
            break
        name = entry.name
        if name.startswith(".") and not prefix.startswith("."):
            continue
        if not name.lower().startswith(lowered) or name == prefix:
            continue
        try:
            if entry.is_dir():
                out.append(os.path.join(parent, name))
        except OSError:
            pass
    return out


def main():
    print(json.dumps(complete(sys.argv[1] if len(sys.argv) > 1 else "")))


if __name__ == "__main__":
    main()
