#!/usr/bin/env python3
"""Previews for the tiled switcher.

Reads [{"id", "transcript"}] from argv[1], and optionally the theme for rendered
markdown from argv[2] (see mdhtml.DEFAULT_STYLE). Prints {id: {"rev", "items"}}: the
last few turns of the transcript, oldest first, as Claude Code lays them out:
{"kind": "user" | "assistant" | "tool" | "result", "text", ...}, with assistant text
as rich-text "html", tools as text = name plus "arg", and results with "error".
`rev` changes only when the transcript (or the theme) does, so the caller can keep
what it already laid out.

Every tile is rendered this way, so no terminal screenshot is taken.
"""
import hashlib
import json
import os
import sys

import mdhtml

TAIL_BYTES = 128 * 1024
# Screenshots and big tool results bloat the tail; read further back up to this.
MAX_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 24
MAX_CHARS = 400
# Assistant replies keep their markdown up to this many lines / characters.
MAX_LINES = 14
MAX_MARKDOWN = 1200
MAX_TABLE_ROWS = 6
# Bump when the output changes shape, so cached previews are thrown away.
VERSION = 2
CACHE = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "claude-sessions-previews.json")
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


def items_of(entry, style=None):
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
                out.append({"kind": "assistant", "html": mdhtml.to_html(text, MAX_LINES, MAX_MARKDOWN, MAX_TABLE_ROWS, style)})
        elif block.get("type") == "tool_use":
            name, arg = tool_call(block, cwd)
            out.append({"kind": "tool", "text": name, "arg": arg, "id": block.get("id"), "state": "running"})
        elif block.get("type") == "tool_result":
            out.append({"kind": "result", "text": result_text(block), "error": bool(block.get("is_error")),
                        "for": block.get("tool_use_id")})
    return out


def preview(path, style=None):
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
                items.extend(items_of(entry, style))
        if len(items) >= MAX_ITEMS or whole or size_hint >= MAX_BYTES:
            # A call's bullet shows how it went, like Claude Code's green / red dot.
            calls = {i["id"]: i for i in items if i["kind"] == "tool" and i.get("id")}
            for item in items:
                if item["kind"] == "result" and item.get("for") in calls:
                    calls[item["for"]]["state"] = "error" if item["error"] else "ok"
            return items[-MAX_ITEMS:]
        size_hint *= 4


def revision(path, style_key):
    try:
        st = os.stat(path)
    except OSError:
        return "missing:" + style_key
    return "%d:%d:%s" % (st.st_mtime_ns, st.st_size, style_key)


def load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            cache = json.load(f)
        return cache if isinstance(cache, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(cache):
    tmp = CACHE + ".%d" % os.getpid()
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp, CACHE)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def main():
    sessions = json.loads(sys.argv[1])
    style = json.loads(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else {}
    style_key = hashlib.sha1(json.dumps([VERSION, style], sort_keys=True).encode()).hexdigest()[:12]
    # Unchanged transcripts are not read again: a preview is kept per transcript
    # path, keyed on its mtime, size and the theme.
    cache, fresh, out = load_cache(), {}, {}
    for s in sessions:
        path = s.get("transcript") or ""
        rev = revision(path, style_key)
        hit = cache.get(path)
        if not (isinstance(hit, dict) and hit.get("rev") == rev and isinstance(hit.get("items"), list)):
            hit = {"rev": rev, "items": preview(path, style)}
        fresh[path] = hit
        out[s["id"]] = hit
    if fresh != cache:
        save_cache(fresh)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
