#!/usr/bin/env python3
"""Start Claude Code in the global quick-launch tmux session, silently.

Reads {"cwd", "prompt", "model", "effort"} from argv[1]:
  cwd     directory to start in (~ is expanded); when empty, a new /tmp/<uuid>
          directory is created so each session gets its own
  prompt  first message for Claude; empty starts an idle session
  model   --model alias or full name; empty or "default" uses Claude's own choice
  effort  --effort level; empty leaves Claude's own default

There is one tmux session, SESSION, shared by every quick launch. The first launch
creates it; later launches add a window to it. Windows are created detached, so no
terminal opens and no client is switched. Sessions started here live in tmux, so the
widget can jump to them like any other tmux session.
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import uuid

SESSION = "claude-quick"
WINDOW = "claude"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
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


def command(prompt, model="", effort=""):
    args = [claude_binary()]
    if model and model != "default":
        if model.startswith("-"):
            raise OSError(f"bad model: {model}")
        args += ["--model", model]
    if effort:
        if effort not in EFFORTS:
            raise OSError(f"bad effort: {effort}")
        args += ["--effort", effort]
    # `--` keeps a prompt starting with "-" from being read as a flag.
    return [*args, "--", prompt] if prompt else args


def tmux(*args):
    result = subprocess.run(["tmux", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or f"tmux {args[0]} failed")


def has_session():
    # Also false when no tmux server is running yet, which new-session handles.
    return subprocess.run(["tmux", "has-session", "-t", "=" + SESSION],
                          capture_output=True).returncode == 0


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
    model = (request.get("model") or "").strip()
    effort = (request.get("effort") or "").strip()
    # tmux runs this string through the shell, so quote every argument.
    shell_command = shlex.join(command(prompt, model, effort))
    if has_session():
        # Trailing colon: a new window at the next free index in that session.
        tmux("new-window", "-d", "-t", "=" + SESSION + ":", "-c", cwd, "-n", WINDOW, shell_command)
    else:
        tmux("new-session", "-d", "-s", SESSION, "-c", cwd, "-n", WINDOW, shell_command)


def main():
    try:
        launch(json.loads(sys.argv[1]))
    except (IndexError, ValueError, OSError) as e:
        print(f"claude-sessions launch: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
