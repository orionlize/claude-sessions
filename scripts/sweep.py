#!/usr/bin/env python3
"""Report which sessions are alive and which were interrupted.

Esc in the terminal fires no hook, so the transcript is the only signal for it.
Reads [{"id", "pid", "transcript"}] from argv[1]; prints one JSON object.
"""
import json
import os
import sys
from datetime import datetime

TAIL_BYTES = 256 * 1024
MARKER = "[Request interrupted by user"


def alive(pid):
    return isinstance(pid, int) and pid > 0 and os.path.isdir(f"/proc/{pid}")


def text_of(message):
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
    return ""


def is_tool_result(message):
    content = message.get("content")
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def interrupted_at(path):
    """Epoch ms of a trailing interruption marker, or 0."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - TAIL_BYTES))
            lines = f.read().split(b"\n")
    except OSError:
        return 0
    for raw in reversed(lines):
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if entry.get("type") not in ("user", "assistant"):
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        if entry["type"] == "assistant":
            return 0
        if is_tool_result(message):
            return 0
        if text_of(message).startswith(MARKER):
            try:
                stamp = entry["timestamp"].replace("Z", "+00:00")
                return int(datetime.fromisoformat(stamp).timestamp() * 1000)
            except (KeyError, AttributeError, ValueError):
                return 0
        return 0
    return 0


def main():
    sessions = json.loads(sys.argv[1])
    print(json.dumps({
        "alive": {s["id"]: alive(s.get("pid")) for s in sessions},
        "interrupted": {s["id"]: interrupted_at(s.get("transcript") or "") for s in sessions},
    }))


if __name__ == "__main__":
    main()
