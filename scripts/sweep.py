#!/usr/bin/env python3
"""Report which sessions are alive and which were interrupted.

Esc in the terminal fires no hook, so the transcript is the only signal for it.
Also reports each session's terminal title: its tmux pane title when inside
tmux, else the title of the niri window that hosts it.
Reads [{"id", "pid", "transcript", "tmux", "pane"}] from argv[1]; prints one JSON object.
"""
import json
import os
import re
import subprocess
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


# Claude prefixes its title with a status glyph ("✳ ", a braille spinner frame).
GLYPH = re.compile(r"^[^\w\s]+\s+")


def clean_title(title):
    return GLYPH.sub("", (title or "").strip()).strip()


def parent(pid):
    with open(f"/proc/{pid}/stat") as f:
        return int(f.read().rsplit(")", 1)[1].split()[1])


def ancestors(pid):
    chain = []
    while pid > 1 and len(chain) < 64:
        chain.append(pid)
        try:
            pid = parent(pid)
        except (OSError, ValueError, IndexError):
            break
    return chain


def run(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=2, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def tmux_title(tmux, pane):
    out = run(["tmux", "-S", tmux.split(",", 1)[0], "display-message", "-p", "-t", pane, "#{pane_title}"])
    return clean_title(out) if out is not None else ""


def is_background_job(pid):
    """A job under Claude's daemon: the terminal above it is not the one showing it."""
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            return b"\0CLAUDE_CODE_SESSION_KIND=bg\0" in b"\0" + f.read()
    except OSError:
        return False


def window_titles(sessions):
    """{id: title} for sessions outside tmux, from niri's window list."""
    local = [s for s in sessions if not (s.get("tmux") and s.get("pane")) and alive(s.get("pid"))
             and not is_background_job(s["pid"])]
    if not local:
        return {}
    out = run(["niri", "msg", "--json", "windows"])
    try:
        windows = json.loads(out) if out else []
    except ValueError:
        return {}
    by_pid = {w.get("pid"): w.get("title") or "" for w in windows if w.get("pid")}
    titles = {}
    for s in local:
        for pid in ancestors(s["pid"]):
            if pid in by_pid:
                titles[s["id"]] = clean_title(by_pid[pid])
                break
    return titles


def titles_of(sessions):
    titles = window_titles(sessions)
    for s in sessions:
        if s.get("tmux") and s.get("pane") and alive(s.get("pid")):
            titles[s["id"]] = tmux_title(s["tmux"], s["pane"])
    return {k: v for k, v in titles.items() if v}


def main():
    sessions = json.loads(sys.argv[1])
    print(json.dumps({
        "alive": {s["id"]: alive(s.get("pid")) for s in sessions},
        "interrupted": {s["id"]: interrupted_at(s.get("transcript") or "") for s in sessions},
        "titles": titles_of(sessions),
    }))


if __name__ == "__main__":
    main()
