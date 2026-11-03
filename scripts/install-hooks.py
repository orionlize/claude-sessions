#!/usr/bin/env python3
"""Add or remove this plugin's hooks in ~/.claude/settings.json.

Usage: install-hooks.py install|uninstall|status
Other hooks are left alone. Our entries are found by the hook script's file name.
"""
import json
import os
import shutil
import sys
import tempfile

HOOK_NAME = "claude-sessions-hook.py"
LEGACY_HOOK_NAMES = ["claude-widget-hook.py"]
EVENTS = [
    "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PostToolUseFailure", "PermissionDenied", "Notification", "Stop", "StopFailure",
    "PreCompact", "PostCompact",
]
PERMISSION_EVENT = "PermissionRequest"
PERMISSION_TIMEOUT = 86400


def settings_path():
    root = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return os.path.join(root, "settings.json")


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save(path, settings):
    if os.path.exists(path):
        shutil.copy2(path, path + ".claude-sessions.bak")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".settings-")
    with os.fdopen(fd, "w") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")
    if os.path.exists(path):
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def is_ours(handler):
    command = str(handler.get("command", ""))
    return any(name in command for name in [HOOK_NAME] + LEGACY_HOOK_NAMES)


def strip(settings):
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return
    for event in list(hooks):
        kept = []
        for group in hooks[event]:
            handlers = [h for h in group.get("hooks", []) if not is_ours(h)]
            if handlers:
                kept.append({**group, "hooks": handlers})
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        del settings["hooks"]


def install(settings, script):
    strip(settings)
    hooks = settings.setdefault("hooks", {})
    command = f"python3 -S {script}"
    for event in EVENTS:
        hooks.setdefault(event, []).append(
            {"hooks": [{"type": "command", "command": command, "timeout": 5}]}
        )
    hooks.setdefault(PERMISSION_EVENT, []).append(
        {"hooks": [{"type": "command", "command": command, "timeout": PERMISSION_TIMEOUT}]}
    )


def installed(settings):
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    return all(
        any(is_ours(h) for g in hooks.get(e, []) for h in g.get("hooks", []))
        for e in EVENTS + [PERMISSION_EVENT]
    )


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    path = settings_path()
    try:
        settings = load(path)
    except ValueError as error:
        print(f"invalid JSON in {path}: {error}", file=sys.stderr)
        return 1
    if action == "status":
        print("installed" if installed(settings) else "missing")
        return 0
    if action == "install":
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "hook", HOOK_NAME)
        install(settings, script)
    elif action == "uninstall":
        strip(settings)
    else:
        print(__doc__, file=sys.stderr)
        return 2
    save(path, settings)
    print("installed" if action == "install" else "missing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
