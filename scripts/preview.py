#!/usr/bin/env python3
"""Previews for the tiled switcher.

Reads [{"id", "pid", "tmux", "pane", "transcript"}] from argv[1] and prints
{id: {"screen", "items"}}, trying each in turn:

- `screen`: a snapshot of the session's tmux pane as {"html", "cols", "rows"}.
- `items`: the last few turns of the transcript, oldest first, as Claude Code lays
  them out: {"kind": "user" | "assistant" | "tool" | "result", "text", ...}, with
  assistant text as markdown, tools as text = name plus "arg", and results with "error".

Terminals outside tmux get no screenshot: niri's screenshot-window always posts a
"Screenshot captured" notification and copies the image to the clipboard.
"""
import html
import json
import os
import re
import subprocess
import sys

from focus import tmux_location

TAIL_BYTES = 128 * 1024
# Screenshots and big tool results bloat the tail; read further back up to this.
MAX_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 24
MAX_CHARS = 400
# Assistant replies keep their markdown up to this many lines / characters.
MAX_LINES = 14
MAX_MARKDOWN = 1200
MAX_TABLE_ROWS = 6
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


HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$", re.M)
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


def open_blocks(lines):
    """Qt's markdown, unlike GitHub's, will not let a table interrupt a paragraph:
    put a blank line before each table header that follows text."""
    out = []
    for i, line in enumerate(lines):
        header = "|" in line and i + 1 < len(lines) and TABLE_RULE.match(lines[i + 1]) and "-" in lines[i + 1]
        if header and out and out[-1].strip() and "|" not in out[-1]:
            out.append("")
        out.append(line)
    return out


def clip_markdown(text):
    """Keep the line breaks markdown needs, but only the first MAX_LINES lines.

    Headings become bold lines, as Claude Code prints them, instead of big type.
    """
    # The blank line keeps a table or list right under a heading from joining its paragraph.
    lines = open_blocks(HEADING.sub(r"**\1**\n", text.strip()).split("\n"))
    out, size, count = [], 0, 0
    for i, line in enumerate(lines):
        # Blank lines are free; a table cut at its header keeps a few rows.
        in_table = "|" in line and ((out and "|" in out[-1]) or
                                    (i + 1 < len(lines) and TABLE_RULE.match(lines[i + 1]) and "-" in lines[i + 1]))
        if line.strip() and count >= MAX_LINES and not (in_table and count < MAX_LINES + MAX_TABLE_ROWS):
            out += ["", "…"]
            break
        if size + len(line) > MAX_MARKDOWN:
            out.append(line[:max(0, MAX_MARKDOWN - size)] + "…")
            break
        out.append(line)
        size += len(line) + 1
        count += 1 if line.strip() else 0
    # An unclosed code fence would swallow everything after it.
    if sum(1 for line in out if line.lstrip().startswith("```")) % 2:
        out.append("```")
    return "\n".join(out)


def short_path(path, cwd):
    if cwd and path.startswith(cwd.rstrip("/") + "/"):
        return path[len(cwd.rstrip("/")) + 1:]
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home + "/") else path


# The argument Claude Code shows in Tool(argument), per tool.
TOOL_ARG = {
    "Bash": "command", "Read": "file_path", "Write": "file_path", "Edit": "file_path",
    "MultiEdit": "file_path", "NotebookEdit": "notebook_path", "Grep": "pattern", "Glob": "pattern",
    "WebFetch": "url", "WebSearch": "query", "Agent": "description", "Task": "description",
    "Skill": "skill",
}
TOOL_LABEL = {"Grep": "Search", "TodoWrite": "Update Todos"}


def tool_call(block, cwd):
    """(name, argument) as Claude Code prints a tool call: `Name(argument)`."""
    name = block.get("name") or "tool"
    args = block.get("input") if isinstance(block.get("input"), dict) else {}
    if name.startswith("mcp__"):
        parts = name.split("__")
        label = " - ".join(parts[1:3]) + " (MCP)"
    else:
        label = TOOL_LABEL.get(name, name)
    key = TOOL_ARG.get(name)
    value = args.get(key) if key else None
    if not value:
        value = next((args[k] for k in ("description", "command", "file_path", "pattern", "url",
                                        "query", "prompt", "path") if args.get(k)), "")
    value = str(value)
    if key in ("file_path", "notebook_path"):
        value = short_path(value, cwd)
    elif key == "pattern" and name == "Grep":
        value = f'pattern: "{value}"'
    value = value.strip().split("\n")[0]
    return clip(label), clip(value) if value else ""


def result_text(block):
    content = block.get("content")
    if isinstance(content, list):
        content = "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    lines = [line for line in str(content or "").split("\n") if line.strip()]
    if not lines:
        return "(No content)"
    first = clip(lines[0])
    return first + (f" … +{len(lines) - 1} lines" if len(lines) > 1 else "")


def items_of(entry):
    """Items in Claude Code's terms: `user` prompts, `assistant` markdown, `tool` calls
    with `arg` and a `state` of running / ok / error, and each call's `result`."""
    kind = entry.get("type")
    message = entry.get("message")
    if kind not in ("user", "assistant") or not isinstance(message, dict) or entry.get("isMeta"):
        return []
    content = message.get("content")
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return []
    cwd = entry.get("cwd") or ""
    out = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = block.get("text", "").strip()
            if not text or (kind == "user" and text.startswith(SYNTHETIC)):
                continue
            if kind == "user":
                lines = text.split("\n")
                text = "\n".join(clip(line) for line in lines[:4]) + ("\n…" if len(lines) > 4 else "")
                out.append({"kind": "user", "text": text})
            else:
                out.append({"kind": "assistant", "text": clip_markdown(text)})
        elif block.get("type") == "tool_use":
            name, arg = tool_call(block, cwd)
            out.append({"kind": "tool", "text": name, "arg": arg, "id": block.get("id"), "state": "running"})
        elif block.get("type") == "tool_result":
            out.append({"kind": "result", "text": result_text(block), "error": bool(block.get("is_error")),
                        "for": block.get("tool_use_id")})
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
            # A call's bullet shows how it went, like Claude Code's green / red dot.
            calls = {i["id"]: i for i in items if i["kind"] == "tool" and i.get("id")}
            for item in items:
                if item["kind"] == "result" and item.get("for") in calls:
                    calls[item["for"]]["state"] = "error" if item["error"] else "ok"
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


def main():
    sessions = json.loads(sys.argv[1])
    out = {}
    for s in sessions:
        screen = snapshot(s)
        out[s["id"]] = {
            "screen": screen,
            "items": [] if screen else preview(s.get("transcript") or ""),
        }
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
