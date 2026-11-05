#!/usr/bin/env python3
"""Previews for the tiled switcher.

Reads [{"id", "transcript"}] from argv[1] and prints {id: {"items"}}: the last few
turns of the transcript, oldest first, as Claude Code lays them out:
{"kind": "user" | "assistant" | "tool" | "result", "text", ...}, with assistant text
as markdown, tools as text = name plus "arg", and results with "error".

Every tile is rendered this way, so no terminal screenshot is taken.
"""
import json
import os
import re
import sys

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


def main():
    sessions = json.loads(sys.argv[1])
    out = {s["id"]: {"items": preview(s.get("transcript") or "")} for s in sessions}
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
