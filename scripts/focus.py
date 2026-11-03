#!/usr/bin/env python3
"""Bring a Claude session to the front: its tmux window and pane, then its terminal window.

Reads {"pid", "tmux", "pane"} from argv[1]. `tmux` and `pane` are the session's
$TMUX and $TMUX_PANE; when missing they are read from /proc/<pid>/environ.
Only niri is supported for focusing the terminal window.
"""
import json
import os
import subprocess
import sys

TERMINAL = os.environ.get("CLAUDE_SESSIONS_TERMINAL") or os.environ.get("CLAUDE_WIDGET_TERMINAL") or "foot"


def parent(pid):
    with open(f"/proc/{pid}/stat") as f:
        return int(f.read().rsplit(")", 1)[1].split()[1])


def ancestors(pid):
    """pid and its ancestors, nearest first."""
    chain = []
    while pid > 1 and len(chain) < 64:
        chain.append(pid)
        try:
            pid = parent(pid)
        except (OSError, ValueError, IndexError):
            break
    return chain


def environ(pid):
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            raw = f.read()
    except OSError:
        return {}
    pairs = (item.split(b"=", 1) for item in raw.split(b"\0") if b"=" in item)
    return {k.decode(errors="replace"): v.decode(errors="replace") for k, v in pairs}


def tmux_location(target):
    """(socket, pane) or None when the session is not inside tmux."""
    tmux, pane = target.get("tmux") or "", target.get("pane") or ""
    if not (tmux and pane) and target.get("pid"):
        env = environ(target["pid"])
        tmux, pane = env.get("TMUX", ""), env.get("TMUX_PANE", "")
    if not (tmux and pane):
        return None
    return tmux.split(",", 1)[0], pane


def pick_client(clients, session):
    """Prefer a client already showing `session`, then the most recently used one."""
    if not clients:
        return None
    return min(clients, key=lambda c: (c["session"] != session, -c["activity"]))


def parse_clients(text):
    clients = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        try:
            clients.append({"pid": int(parts[0]), "tty": parts[1], "session": parts[2], "activity": int(parts[3] or 0)})
        except ValueError:
            continue
    return clients


def find_window(windows, pids):
    by_pid = {w.get("pid"): w for w in windows if w.get("pid")}
    for pid in pids:
        if pid in by_pid:
            return by_pid[pid]
    return None


class Runner:
    def __init__(self, socket=None):
        self.socket = socket

    def tmux(self, *args):
        return subprocess.run(["tmux", "-S", self.socket, *args], capture_output=True, text=True, check=True).stdout

    def niri_windows(self):
        out = subprocess.run(["niri", "msg", "--json", "windows"], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def focus_window(self, window_id):
        subprocess.run(["niri", "msg", "action", "focus-window", "--id", str(window_id)], check=True)

    def spawn_terminal(self, session):
        subprocess.Popen([TERMINAL, "tmux", "-S", self.socket, "attach-session", "-t", "=" + session],
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def focus(target, runner=None):
    """Returns what happened: "focused", "spawned" or "not-found"."""
    pid = target.get("pid")
    location = tmux_location(target)
    terminal_pids = ancestors(pid) if isinstance(pid, int) and pid > 0 else []

    if location:
        socket, pane = location
        runner = runner or Runner(socket)
        session, window = runner.tmux("display-message", "-p", "-t", pane, "#{session_name}\t#{window_id}").strip().split("\t")
        client = pick_client(parse_clients(runner.tmux(
            "list-clients", "-F", "#{client_pid}\t#{client_tty}\t#{client_session}\t#{client_activity}")), session)
        if client and client["session"] != session:
            runner.tmux("switch-client", "-c", client["tty"], "-t", "=" + session)
        runner.tmux("select-window", "-t", window)
        runner.tmux("select-pane", "-t", pane)
        if not client:
            runner.spawn_terminal(session)
            return "spawned"
        terminal_pids = ancestors(client["pid"])

    runner = runner or Runner()
    window = find_window(runner.niri_windows(), terminal_pids)
    if not window:
        return "not-found"
    runner.focus_window(window["id"])
    return "focused"


def main():
    try:
        result = focus(json.loads(sys.argv[1]))
    except (IndexError, ValueError, OSError, subprocess.CalledProcessError) as e:
        print(f"claude-sessions focus: {e}", file=sys.stderr)
        sys.exit(1)
    print(result)
    sys.exit(0 if result != "not-found" else 1)


if __name__ == "__main__":
    main()
