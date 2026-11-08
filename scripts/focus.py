#!/usr/bin/env python3
"""Bring a Claude session to the front: its tmux window and pane, then its terminal window.

Reads {"pid", "tmux", "pane"} from argv[1]. `tmux` and `pane` are the session's
$TMUX and $TMUX_PANE; when missing they are read from /proc/<pid>/environ.
A background job (`claude --bg`, or one pushed to the background) runs under Claude's
daemon with no terminal of its own: it is shown by the terminal running
`claude attach <id>`, and one is opened when none is.
Only niri is supported for focusing the terminal window.
"""
import json
import os
import re
import shutil
import subprocess
import sys

TERMINAL = os.environ.get("CLAUDE_SESSIONS_TERMINAL") or os.environ.get("CLAUDE_WIDGET_TERMINAL") or "foot"
# Wrappers that run Claude Code unchanged and are what people type as `claude`.
WRAPPERS = ("claude-hl",)


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


def cmdline(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
    except OSError:
        return []


def claude_binary(pid):
    """The binary that runs the daemon hosting `pid`, so attach talks to the same install."""
    for ancestor in ancestors(pid):
        argv = cmdline(ancestor)
        if argv[1:3] == ["daemon", "run"]:
            return argv[0]
    return "claude"


def attach_command(claude, env):
    """What the attach terminal runs: $CLAUDE_SESSIONS_CLAUDE, else a wrapper on the
    job's PATH (shell aliases are invisible here), else the daemon's own binary."""
    chosen = env.get("CLAUDE_SESSIONS_CLAUDE")
    if chosen:
        return chosen
    for wrapper in WRAPPERS:
        found = shutil.which(wrapper, path=env.get("PATH"))
        if found:
            return found
    return claude


def job_of(agents, pid):
    """The `claude agents` entry of the background job running as `pid`, or None."""
    for agent in agents:
        if isinstance(agent, dict) and agent.get("pid") == pid and agent.get("kind") == "background" and agent.get("id"):
            return agent
    return None


# Claude prefixes its title with a status glyph ("✳ ", a braille spinner frame).
GLYPH = re.compile(r"^[^\w\s]+\s+")


def clean_title(title):
    return GLYPH.sub("", (title or "").strip()).strip()


def client_pids(procs):
    """Interactive Claude processes: the agent view, a session or `claude attach`."""
    found = []
    for pid, argv in procs:
        if argv and os.path.basename(argv[0]) == "claude" and not (
                len(argv) > 1 and (argv[1] == "daemon" or argv[1].startswith("bg-"))):
            found.append(pid)
    return found


def showing_window(windows, name, clients):
    """The window of a Claude client whose title says it is showing job `name`."""
    if not name:
        return None
    hosting = [w for w in windows if clean_title(w.get("title")) == name]
    for pid in clients:
        window = find_window(hosting, ancestors(pid))
        if window:
            return window
    return None


def attach_pids(job, procs):
    """Processes already running `claude attach <job>`, from (pid, argv) pairs."""
    found = []
    for pid, argv in procs:
        if "attach" in argv and argv.index("attach") + 1 < len(argv) and argv[argv.index("attach") + 1] == job:
            found.append(pid)
    return found


def processes():
    for name in os.listdir("/proc"):
        if name.isdigit():
            yield int(name), cmdline(int(name))


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

    def agents(self, claude, env):
        out = subprocess.run([claude, "agents", "--json"], capture_output=True, text=True,
                             check=True, timeout=5, env=env).stdout
        return json.loads(out)

    def spawn_attach(self, claude, job, cwd, env):
        subprocess.Popen([TERMINAL, attach_command(claude, env), "attach", job], cwd=cwd if os.path.isdir(cwd or "") else None,
                         env=env, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def spawn_terminal(self, session):
        subprocess.Popen([TERMINAL, "tmux", "-S", self.socket, "attach-session", "-t", "=" + session],
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def job_env(job_environ):
    """Our environment plus what decides which Claude install and account the job uses."""
    env = dict(os.environ)
    for key in ("PATH", "CLAUDE_CONFIG_DIR"):
        if job_environ.get(key):
            env[key] = job_environ[key]
    return env


def focus_job(pid, job_environ, runner):
    """Focus or open the terminal attached to background job `pid`; None if it is not one."""
    claude = claude_binary(pid)
    env = job_env(job_environ)
    agent = job_of(runner.agents(claude, env), pid)
    if not agent:
        return None
    job = agent["id"]
    procs = list(processes())
    windows = runner.niri_windows()
    # The agent view or an attach shows the job's name as its title while the job is on screen.
    window = showing_window(windows, agent.get("name"), client_pids(procs))
    # An attach still running for it, though the title gives no name to go by.
    for attached in attach_pids(job, procs):
        window = window or find_window(windows, ancestors(attached))
    if window:
        runner.focus_window(window["id"])
        return "focused"
    runner.spawn_attach(claude, job, job_environ.get("PWD", ""), env)
    return "spawned"


def focus(target, runner=None):
    """Returns what happened: "focused", "spawned" or "not-found"."""
    pid = target.get("pid")
    # Its ancestors lead to whichever terminal started the daemon, which may be
    # showing the agent view or another job by now.
    if isinstance(pid, int) and pid > 0:
        job_environ = environ(pid)
        if job_environ.get("CLAUDE_CODE_SESSION_KIND") == "bg":
            result = focus_job(pid, job_environ, runner or Runner())
            if result:
                return result
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
    except (IndexError, ValueError, OSError, subprocess.SubprocessError) as e:
        print(f"claude-sessions focus: {e}", file=sys.stderr)
        sys.exit(1)
    print(result)
    sys.exit(0 if result != "not-found" else 1)


if __name__ == "__main__":
    main()
