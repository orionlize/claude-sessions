#!/usr/bin/env python3
"""Claude Code hook: forwards events to the DMS plugin over a Unix socket.

For PermissionRequest it stays connected until the widget replies. Every failure
path exits 0 with no output, so Claude Code falls back to its terminal prompt.
"""
import hashlib
import json
import os
import socket
import sys
import uuid

MAX_DETAIL = 6000
MAX_ACTIVITY = 120
PERSISTABLE_UPDATES = {"addRules", "addDirectories"}


def socket_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(runtime, "claude-sessions.sock")


def claude_pid():
    """Find the Claude process; an intermediate shell may sit between us."""
    pid = os.getppid()
    for _ in range(5):
        try:
            with open(f"/proc/{pid}/comm") as f:
                comm = f.read().strip()
            if comm in ("claude", "node", "bun"):
                return pid
            with open(f"/proc/{pid}/stat") as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
        if pid <= 1:
            break
    return os.getppid()


def clip(value, limit):
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "\n… [truncated]"


def summarize_tool(name, tool_input):
    """Text the user reads before approving; it must show what will really run."""
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if name == "Bash":
        return str(tool_input.get("command", ""))
    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Read"):
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        if "old_string" in tool_input:
            return f"{path}\n--- old\n{tool_input.get('old_string')}\n+++ new\n{tool_input.get('new_string')}"
        if "content" in tool_input:
            return f"{path}\n{tool_input.get('content')}"
        if "new_source" in tool_input:
            return f"{path}\n{tool_input.get('new_source')}"
        return path
    if name == "WebFetch":
        return str(tool_input.get("url", ""))
    if name == "WebSearch":
        return str(tool_input.get("query", ""))
    if name == "AskUserQuestion":
        questions = tool_input.get("questions") or [{}]
        return str(questions[0].get("question", ""))
    if name == "ExitPlanMode":
        return str(tool_input.get("plan", ""))
    if name in ("Task", "Agent"):
        return f"{tool_input.get('description', '')}\n{tool_input.get('prompt', '')}".strip()
    return json.dumps(tool_input, ensure_ascii=False, indent=2)


def fingerprint(name, tool_input):
    raw = json.dumps([name, tool_input], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()


def always_rules(suggestions):
    """Keep persistent grants only; "always allow" must not switch the session mode."""
    if not isinstance(suggestions, list):
        return []
    return [s for s in suggestions if isinstance(s, dict) and s.get("type") in PERSISTABLE_UPDATES]


def always_label(rules):
    labels = []
    for rule in rules:
        for item in rule.get("rules") or []:
            tool = item.get("toolName", "")
            content = item.get("ruleContent")
            labels.append(f"{tool}({content})" if content else tool)
        labels.extend(rule.get("directories") or [])
    return ", ".join(labels)


def build_event(data):
    name = data.get("hook_event_name", "")
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input")
    event = {
        "event": name,
        "session_id": data.get("session_id", ""),
        "cwd": data.get("cwd", ""),
        "transcript_path": data.get("transcript_path", ""),
        "pid": claude_pid(),
        "permission_mode": data.get("permission_mode", ""),
        "is_subagent": bool(data.get("agent_id")),
    }
    # Lets the widget jump to the tmux pane that hosts this session.
    if os.environ.get("TMUX") and os.environ.get("TMUX_PANE"):
        event["tmux"] = os.environ["TMUX"]
        event["tmux_pane"] = os.environ["TMUX_PANE"]
    if data.get("session_title"):
        event["title"] = clip(data["session_title"], 80)
    if data.get("source"):
        event["source"] = data["source"]
    if data.get("trigger"):
        event["trigger"] = data["trigger"]
    if name == "UserPromptSubmit":
        event["prompt"] = clip(data.get("prompt"), MAX_ACTIVITY)
    if name == "Notification":
        event["notification_type"] = data.get("notification_type", "")
        event["message"] = clip(data.get("message"), 300)
    if name == "StopFailure":
        event["message"] = clip(data.get("error"), 300)
    if tool:
        event["tool_name"] = tool
        event["tool_use_id"] = data.get("tool_use_id", "")
        event["fingerprint"] = fingerprint(tool, tool_input)
        event["activity"] = clip(summarize_tool(tool, tool_input).split("\n", 1)[0], MAX_ACTIVITY)
    return event


def build_request(event, data):
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input")
    event["request_id"] = uuid.uuid4().hex
    if tool == "AskUserQuestion" and isinstance(tool_input, dict):
        event["kind"] = "question"
        event["questions"] = tool_input.get("questions") or []
    else:
        rules = always_rules(data.get("permission_suggestions"))
        event["kind"] = "permission"
        event["detail"] = clip(summarize_tool(tool, tool_input), MAX_DETAIL)
        event["always_label"] = clip(always_label(rules), 200) if rules else ""
    return event


def decision_output(reply, data):
    action = reply.get("action")
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input")
    if action == "allow":
        decision = {"behavior": "allow"}
    elif action == "always":
        rules = always_rules(data.get("permission_suggestions"))
        decision = {"behavior": "allow"}
        if rules:
            decision["updatedPermissions"] = rules
    elif action == "answer" and isinstance(tool_input, dict) and isinstance(reply.get("answers"), dict):
        decision = {"behavior": "allow", "updatedInput": {**tool_input, "answers": reply["answers"]}}
    elif action == "deny":
        declined_question = tool == "AskUserQuestion"
        decision = {
            "behavior": "deny",
            "message": "The user declined to answer." if declined_question
            else "The user denied this from the desktop widget.",
            # Same as "No" in the terminal: stop and wait instead of trying another route.
            "interrupt": not declined_question,
        }
    else:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}


def read_line(sock):
    buffer = b""
    while b"\n" not in buffer:
        chunk = sock.recv(65536)
        if not chunk:
            return None
        buffer += chunk
    return buffer.split(b"\n", 1)[0]


def main():
    data = json.load(sys.stdin)
    event = build_event(data)
    waits = event["event"] == "PermissionRequest"
    if waits:
        build_request(event, data)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        sock.connect(socket_path())
        sock.sendall(json.dumps(event, ensure_ascii=False).encode() + b"\n")
        if not waits:
            return
        sock.settimeout(None)
        line = read_line(sock)
    if line is None:
        return
    output = decision_output(json.loads(line), data)
    if output:
        print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
