#!/usr/bin/env python3
"""Previews for the tiled switcher.

Reads [{"id", "pid", "tmux", "pane", "transcript"}] from argv[1] and prints
{id: {"screen", "shot", "items"}}, trying each in turn:

- `screen`: a snapshot of the session's tmux pane as {"html", "cols", "rows"}.
- `shot`: outside tmux, the path of a screenshot of its terminal window. Only taken
  when argv[2] is "shots", because niri also puts every screenshot on the
  clipboard: the clipboard is put back afterwards through DMS's clipboard history.
- `items`: the last few turns of the transcript as [{"kind", "text"}], kind being
  "user", "assistant" or "tool", oldest first.
"""
import html
import json
import os
import re
import subprocess
import sys
import time

from focus import ancestors, find_window, tmux_location

SHOT_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "claude-sessions-shots")

TAIL_BYTES = 128 * 1024
# Screenshots and big tool results bloat the tail; read further back up to this.
MAX_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 14
MAX_CHARS = 400
# Prompts Claude Code writes on the user's behalf; not something they typed.
SYNTHETIC = ("<command-", "<local-command", "<system-reminder", "<bash-", "Caveat:")


def tail_lines(path, size_hint):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - size_hint))
            lines = f.read().split(b"\n")
    except OSError:
        return [], True
    # The first line is cut in half unless the read started at the top.
    whole = size <= size_hint
    return (lines if whole else lines[1:]), whole


def clip(text):
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS - 1] + "…"


def tool_summary(block):
    name = block.get("name", "tool")
    args = block.get("input") or {}
    for key in ("description", "command", "file_path", "pattern", "url", "query", "prompt", "path"):
        value = args.get(key) if isinstance(args, dict) else None
        if value:
            return f"{name}: {value}"
    return name


def items_of(entry):
    kind = entry.get("type")
    message = entry.get("message")
    if kind not in ("user", "assistant") or not isinstance(message, dict) or entry.get("isMeta"):
        return []
    content = message.get("content")
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return []
    out = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = block.get("text", "").strip()
            if not text or (kind == "user" and text.startswith(SYNTHETIC)):
                continue
            out.append({"kind": kind, "text": clip(text)})
        elif block.get("type") == "tool_use":
            out.append({"kind": "tool", "text": clip(tool_summary(block))})
    return out


def preview(path):
    size_hint = TAIL_BYTES
    while True:
        lines, whole = tail_lines(path, size_hint)
        items = []
        for raw in lines:
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            if isinstance(entry, dict):
                items.extend(items_of(entry))
        if len(items) >= MAX_ITEMS or whole or size_hint >= MAX_BYTES:
            return items[-MAX_ITEMS:]
        size_hint *= 4


# xterm's 16 colours; 16-255 are computed.
BASIC = ["#000000", "#cd3131", "#0dbc79", "#e5e510", "#2472c8", "#bc3fbc", "#11a8cd", "#e5e5e5",
         "#666666", "#f14c4c", "#23d18b", "#f5f543", "#3b8eea", "#d670d6", "#29b8db", "#ffffff"]
SGR = re.compile(r"\x1b\[([0-9;:]*)m")
OTHER_ESCAPE = re.compile(r"\x1b(\[[0-9;?]*[A-Za-z]|\][^\x07\x1b]*(\x07|\x1b\\)|[()][A-Za-z0-9])")


def color256(n):
    if n < 16:
        return BASIC[n]
    if n >= 232:
        level = 8 + (n - 232) * 10
        return "#%02x%02x%02x" % (level, level, level)
    n -= 16
    steps = [0, 95, 135, 175, 215, 255]
    return "#%02x%02x%02x" % (steps[n // 36], steps[n // 6 % 6], steps[n % 6])


def apply_sgr(state, params):
    codes = [int(c) if c.isdigit() else 0 for c in re.split("[;:]", params)] if params else [0]
    i = 0
    while i < len(codes):
        c = codes[i]
        if c == 0:
            state.clear()
        elif c == 1:
            state["bold"] = True
        elif c == 3:
            state["italic"] = True
        elif c == 4:
            state["underline"] = True
        elif c == 7:
            state["reverse"] = True
        elif c == 22:
            state.pop("bold", None)
        elif c == 23:
            state.pop("italic", None)
        elif c == 24:
            state.pop("underline", None)
        elif c == 27:
            state.pop("reverse", None)
        elif 30 <= c <= 37 or 90 <= c <= 97:
            state["fg"] = BASIC[c - 30 if c < 90 else c - 90 + 8]
        elif 40 <= c <= 47 or 100 <= c <= 107:
            state["bg"] = BASIC[c - 40 if c < 100 else c - 100 + 8]
        elif c == 39:
            state.pop("fg", None)
        elif c == 49:
            state.pop("bg", None)
        elif c in (38, 48) and i + 1 < len(codes):
            key = "fg" if c == 38 else "bg"
            if codes[i + 1] == 5 and i + 2 < len(codes):
                state[key] = color256(codes[i + 2] % 256)
                i += 2
            elif codes[i + 1] == 2 and i + 4 < len(codes):
                state[key] = "#%02x%02x%02x" % tuple(min(255, v) for v in codes[i + 2:i + 5])
                i += 4
        i += 1


def span(text, state):
    text = html.escape(text, quote=False)
    if not state:
        return text
    fg, bg = state.get("fg"), state.get("bg")
    if state.get("reverse"):
        fg, bg = bg or "@BG@", fg or "@FG@"
    style = []
    if fg:
        style.append("color:" + fg)
    if bg:
        style.append("background-color:" + bg)
    if state.get("bold"):
        style.append("font-weight:bold")
    if state.get("italic"):
        style.append("font-style:italic")
    if state.get("underline"):
        style.append("text-decoration:underline")
    return "<span style=\"%s\">%s</span>" % (";".join(style), text) if style else text


def ansi_to_html(text):
    """Terminal text with SGR escapes as Qt rich text, one <br> per line.

    Reversed default colours come out as @FG@ / @BG@ for the caller to fill in.
    """
    out, state = [], {}
    for line in text.split("\n"):
        pos, parts = 0, []
        for m in SGR.finditer(line):
            parts.append(span(OTHER_ESCAPE.sub("", line[pos:m.start()]), state))
            apply_sgr(state, m.group(1))
            pos = m.end()
        parts.append(span(OTHER_ESCAPE.sub("", line[pos:]), state))
        out.append("".join(parts))
    return "<br>".join(out)


def snapshot(target):
    location = tmux_location(target)
    if not location:
        return None
    socket, pane = location
    run = lambda *args: subprocess.run(["tmux", "-S", socket, *args], capture_output=True, text=True,
                                       timeout=2, check=True).stdout
    try:
        cols, rows = run("display-message", "-p", "-t", pane, "#{pane_width}\t#{pane_height}").split()
        text = run("capture-pane", "-p", "-e", "-t", pane)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return {"html": ansi_to_html(text.rstrip("\n")), "cols": int(cols), "rows": int(rows)}


def run(*args, timeout=3):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True).stdout


def clipboard_history():
    try:
        return json.loads(run("dms", "clipboard", "history", "--json")) or []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def restore_clipboard(before, taken):
    """Drop the screenshots niri added to the clipboard history and re-copy what was there.

    The clipboard manager records entries asynchronously, so wait for them briefly.
    """
    newest = max((e.get("id", 0) for e in before), default=0)
    added = []
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        added = [e for e in clipboard_history() if e.get("id", 0) > newest and e.get("isImage")]
        if len(added) >= taken:
            break
        time.sleep(0.1)
    for entry in added:
        try:
            run("dms", "clipboard", "delete", str(entry["id"]))
        except (OSError, subprocess.SubprocessError):
            pass
    if newest:
        try:
            run("dms", "clipboard", "get", str(newest), "--copy")
        except (OSError, subprocess.SubprocessError):
            pass


def screenshots(targets):
    """{session id: png path} for sessions whose terminal window was found."""
    if not targets:
        return {}
    try:
        windows = json.loads(run("niri", "msg", "--json", "windows"))
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    os.makedirs(SHOT_DIR, exist_ok=True)
    for name in os.listdir(SHOT_DIR):
        try:
            os.remove(os.path.join(SHOT_DIR, name))
        except OSError:
            pass
    before = clipboard_history()
    shots, stamp = {}, int(time.time() * 1000)
    for target in targets:
        pid = target.get("pid")
        window = find_window(windows, ancestors(pid)) if isinstance(pid, int) and pid > 0 else None
        if not window:
            continue
        # A fresh name per capture, so the image cache never serves an old one.
        path = os.path.join(SHOT_DIR, f"{window['id']}-{stamp}.png")
        try:
            run("niri", "msg", "action", "screenshot-window", "--id", str(window["id"]),
                "--write-to-disk", "true", "--path", path)
        except (OSError, subprocess.SubprocessError):
            continue
        shots[target["id"]] = path
    if shots:
        restore_clipboard(before, len(shots))
    # niri writes the file shortly after the action returns.
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not all(os.path.exists(p) for p in shots.values()):
        time.sleep(0.05)
    return {k: p for k, p in shots.items() if os.path.exists(p)}


def main():
    sessions = json.loads(sys.argv[1])
    take_shots = len(sys.argv) > 2 and sys.argv[2] == "shots"
    screens = {s["id"]: snapshot(s) for s in sessions}
    shots = screenshots([s for s in sessions if not screens[s["id"]]]) if take_shots else {}
    out = {}
    for s in sessions:
        screen, shot = screens[s["id"]], shots.get(s["id"])
        out[s["id"]] = {
            "screen": screen,
            "shot": shot,
            "items": [] if screen or shot else preview(s.get("transcript") or ""),
        }
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
