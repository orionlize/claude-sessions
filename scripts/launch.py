#!/usr/bin/env python3
"""Open a new terminal window running Claude Code.

Reads {"cwd", "prompt"} from argv[1]:
  cwd     directory to start in (~ is expanded); when empty, a new /tmp/<uuid>
          directory is created so each session gets its own
  prompt  first message for Claude; empty starts an idle session
"""
import json
import os
import shutil
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from focus import TERMINAL  # noqa: E402

CLAUDE_FALLBACKS = ("~/.local/bin/claude", "~/.claude/local/claude", "~/.npm-global/bin/claude")


def claude_binary():
    found = shutil.which("claude")
    if found:
        return found
    for path in CLAUDE_FALLBACKS:
        path = os.path.expanduser(path)
        if os.access(path, os.X_OK):
            return path
    raise OSError("claude not found in PATH")


def command(prompt):
    # `--` keeps a prompt starting with "-" from being read as a flag.
    return [claude_binary(), "--", prompt] if prompt else [claude_binary()]


def launch(request):
    cwd = request.get("cwd")
    if cwd:
        cwd = os.path.expanduser(cwd)
    else:
        cwd = os.path.join("/tmp", str(uuid.uuid4()))
        os.makedirs(cwd)
    if not os.path.isdir(cwd):
        raise OSError(f"not a directory: {cwd}")
    prompt = (request.get("prompt") or "").strip()
    subprocess.Popen([TERMINAL, *command(prompt)], cwd=cwd,
                     start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    try:
        launch(json.loads(sys.argv[1]))
    except (IndexError, ValueError, OSError) as e:
        print(f"claude-sessions launch: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
