import contextlib
import importlib.util
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK = ROOT / "hook" / "claude-sessions-hook.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = load(HOOK, "hook_module")
sweep = load(ROOT / "scripts" / "sweep.py", "sweep_module")
installer = load(ROOT / "scripts" / "install-hooks.py", "installer_module")
focus = load(ROOT / "scripts" / "focus.py", "focus_module")
SUGGESTION = {"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "ls:*"}], "behavior": "allow", "destination": "localSettings"}
MODE = {"type": "setMode", "mode": "acceptEdits", "destination": "session"}
PERMISSION = {
    "hook_event_name": "PermissionRequest", "session_id": "s", "cwd": "/p", "tool_name": "Bash",
    "tool_input": {"command": "ls -la"}, "permission_suggestions": [SUGGESTION, MODE],
}
QUESTION = {
    "hook_event_name": "PermissionRequest", "session_id": "s", "cwd": "/p", "tool_name": "AskUserQuestion",
    "tool_input": {"questions": [{"question": "Q?", "header": "H", "options": [{"label": "A"}, {"label": "B"}]}]},
}


def run_hook(payload, runtime, reply=None, close_without_reply=False):
    path = os.path.join(runtime, "claude-sessions.sock")
    received = {}
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)

    def serve():
        conn, _ = server.accept()
        buffer = b""
        while b"\n" not in buffer:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buffer += chunk
        received["event"] = json.loads(buffer.split(b"\n")[0])
        if reply is not None:
            conn.sendall(json.dumps(reply).encode() + b"\n")
        conn.close()

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        done = subprocess.run(
            [sys.executable, "-S", str(HOOK)], input=json.dumps(payload), capture_output=True, text=True,
            timeout=5, env={**os.environ, "XDG_RUNTIME_DIR": runtime},
        )
        thread.join(2)
    finally:
        server.close()
        os.unlink(path)
    return done, received.get("event")


class HookFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def decision(self, done):
        self.assertEqual(done.returncode, 0)
        return json.loads(done.stdout)["hookSpecificOutput"]["decision"]

    def test_no_socket_is_silent(self):
        done = subprocess.run(
            [sys.executable, "-S", str(HOOK)], input=json.dumps(PERMISSION), capture_output=True, text=True,
            env={**os.environ, "XDG_RUNTIME_DIR": self.tmp.name},
        )
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))

    def test_allow(self):
        done, event = run_hook(PERMISSION, self.tmp.name, {"action": "allow"})
        self.assertEqual(self.decision(done), {"behavior": "allow"})
        self.assertEqual(event["detail"], "ls -la")
        self.assertEqual(event["always_label"], "Bash(ls:*)")

    def test_always_never_changes_mode(self):
        done, _ = run_hook(PERMISSION, self.tmp.name, {"action": "always"})
        self.assertEqual(self.decision(done)["updatedPermissions"], [SUGGESTION])

    def test_deny_interrupts(self):
        done, _ = run_hook(PERMISSION, self.tmp.name, {"action": "deny"})
        decision = self.decision(done)
        self.assertEqual((decision["behavior"], decision["interrupt"]), ("deny", True))

    def test_declined_question_does_not_interrupt(self):
        done, _ = run_hook(QUESTION, self.tmp.name, {"action": "deny"})
        self.assertFalse(self.decision(done)["interrupt"])

    def test_answer_keeps_questions(self):
        done, event = run_hook(QUESTION, self.tmp.name, {"action": "answer", "answers": {"Q?": "B"}})
        updated = self.decision(done)["updatedInput"]
        self.assertEqual(updated["answers"], {"Q?": "B"})
        self.assertEqual(updated["questions"], QUESTION["tool_input"]["questions"])
        self.assertEqual(event["kind"], "question")

    def test_pass_and_close_fall_back_to_terminal(self):
        done, _ = run_hook(PERMISSION, self.tmp.name, {"action": "pass"})
        self.assertEqual(done.stdout, "")
        done, _ = run_hook(PERMISSION, self.tmp.name)
        self.assertEqual(done.stdout, "")

    def test_non_blocking_event_needs_no_reply(self):
        payload = {"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "Bash", "tool_input": {"command": "x\ny"}}
        done, event = run_hook(payload, self.tmp.name)
        self.assertEqual(done.stdout, "")
        self.assertEqual(event["activity"], "x")

    def test_tool_use_id_is_forwarded(self):
        payload = {"hook_event_name": "PostToolUse", "session_id": "s", "tool_name": "Bash", "tool_use_id": "t1", "tool_input": {}}
        _, event = run_hook(payload, self.tmp.name)
        self.assertEqual(event["tool_use_id"], "t1")

    def test_long_detail_says_it_was_truncated(self):
        detail = hook.clip("x" * 7000, hook.MAX_DETAIL)
        self.assertTrue(detail.endswith("[truncated]"))


class Sweep(unittest.TestCase):
    def write(self, *entries):
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        self.addCleanup(os.unlink, f.name)
        f.write("\n".join(json.dumps(e) for e in entries) + "\n")
        f.close()
        return f.name

    def test_trailing_marker(self):
        path = self.write(
            {"type": "assistant", "message": {"content": []}},
            {"type": "user", "timestamp": "2026-10-31T00:00:00.000Z", "message": {"content": [{"type": "text", "text": "[Request interrupted by user for tool use]"}]}},
            {"type": "cost-state"},
        )
        self.assertGreater(sweep.interrupted_at(path), 0)

    def test_later_activity_cancels_marker(self):
        path = self.write(
            {"type": "user", "timestamp": "2026-10-31T00:00:00.000Z", "message": {"content": "[Request interrupted by user]"}},
            {"type": "user", "message": {"content": "continue"}},
        )
        self.assertEqual(sweep.interrupted_at(path), 0)

    def test_missing_file(self):
        self.assertEqual(sweep.interrupted_at("/nonexistent"), 0)

    def test_alive(self):
        self.assertTrue(sweep.alive(os.getpid()))
        self.assertFalse(sweep.alive(None))


class Installer(unittest.TestCase):
    def test_roundtrip_preserves_other_hooks(self):
        foreign = {"matcher": "Bash", "hooks": [{"type": "command", "command": "other.sh"}]}
        settings = {"model": "opus", "hooks": {"PreToolUse": [foreign]}}
        installer.install(settings, "/x/claude-sessions-hook.py")
        installer.install(settings, "/x/claude-sessions-hook.py")
        self.assertTrue(installer.installed(settings))
        self.assertEqual(len(settings["hooks"]["PreToolUse"]), 2)
        self.assertEqual(settings["hooks"]["PermissionRequest"][0]["hooks"][0]["timeout"], 86400)
        installer.strip(settings)
        self.assertEqual(settings, {"model": "opus", "hooks": {"PreToolUse": [foreign]}})

    def test_strip_removes_empty_hooks_key(self):
        settings = {}
        installer.install(settings, "/x/claude-sessions-hook.py")
        installer.strip(settings)
        self.assertEqual(settings, {})


class TmuxEvent(unittest.TestCase):
    def test_tmux_location_is_forwarded(self):
        env = {"TMUX": "/tmp/tmux-1/default,9,0", "TMUX_PANE": "%3"}
        with unittest.mock.patch.dict(os.environ, env):
            event = hook.build_event({"hook_event_name": "Stop", "session_id": "s"})
        self.assertEqual((event["tmux"], event["tmux_pane"]), ("/tmp/tmux-1/default,9,0", "%3"))

    def test_outside_tmux_sends_nothing(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            event = hook.build_event({"hook_event_name": "Stop", "session_id": "s"})
        self.assertNotIn("tmux", event)


class FakeRunner:
    def __init__(self, clients, windows, location="work\t@2"):
        self.calls, self.clients, self.windows, self.location = [], clients, windows, location
        self.focused = self.spawned = None

    def tmux(self, *args):
        self.calls.append(args)
        if args[0] == "display-message":
            return self.location + "\n"
        if args[0] == "list-clients":
            return "".join("\t".join(map(str, c)) + "\n" for c in self.clients)
        return ""

    def niri_windows(self):
        return self.windows

    def focus_window(self, window_id):
        self.focused = window_id

    def spawn_terminal(self, session):
        self.spawned = session


class JobRunner(FakeRunner):
    def __init__(self, agents, windows):
        super().__init__([], windows)
        self.agent_list, self.attached = agents, None

    def agents(self, claude, env):
        return self.agent_list

    def spawn_attach(self, claude, job, cwd, env):
        self.attached = (claude, job, cwd, env)


class Focus(unittest.TestCase):
    target = {"pid": 999999, "tmux": "/tmp/tmux-1/default,9,0", "pane": "%3"}

    def run_focus(self, runner):
        with unittest.mock.patch.object(focus, "ancestors", lambda pid: [pid, pid + 1000]):
            return focus.focus(self.target, runner)

    def test_selects_pane_and_focuses_client_terminal(self):
        runner = FakeRunner([(41, "/dev/pts/0", "work", 5)], [{"id": 7, "pid": 1041}, {"id": 8, "pid": 5}])
        self.assertEqual(self.run_focus(runner), "focused")
        self.assertIn(("select-window", "-t", "@2"), runner.calls)
        self.assertIn(("select-pane", "-t", "%3"), runner.calls)
        self.assertFalse(any(c[0] == "switch-client" for c in runner.calls))
        self.assertEqual(runner.focused, 7)

    def test_prefers_client_on_same_session_then_newest(self):
        clients = [(41, "/dev/pts/0", "other", 99), (42, "/dev/pts/1", "work", 1), (43, "/dev/pts/2", "work", 5)]
        self.assertEqual(focus.pick_client(focus.parse_clients(
            "".join("\t".join(map(str, c)) + "\n" for c in clients)), "work")["pid"], 43)

    def test_switches_client_from_other_session(self):
        runner = FakeRunner([(41, "/dev/pts/0", "other", 5)], [{"id": 7, "pid": 41}])
        self.run_focus(runner)
        self.assertIn(("switch-client", "-c", "/dev/pts/0", "-t", "=work"), runner.calls)

    def test_spawns_terminal_without_client(self):
        runner = FakeRunner([], [])
        self.assertEqual(self.run_focus(runner), "spawned")
        self.assertEqual(runner.spawned, "work")
        self.assertIsNone(runner.focused)

    def test_outside_tmux_walks_up_from_claude(self):
        runner = FakeRunner([], [{"id": 3, "pid": 1000999}])
        with unittest.mock.patch.object(focus, "environ", lambda pid: {}), \
             unittest.mock.patch.object(focus, "ancestors", lambda pid: [pid, pid + 1000]):
            self.assertEqual(focus.focus({"pid": 999999}, runner), "focused")
        self.assertEqual((runner.calls, runner.focused), ([], 3))

    def test_reads_tmux_from_process_environment(self):
        with unittest.mock.patch.object(focus, "environ", lambda pid: {"TMUX": "/s,1,0", "TMUX_PANE": "%9"}):
            self.assertEqual(focus.tmux_location({"pid": 5}), ("/s", "%9"))

    def test_forked_from_reads_resume_target(self):
        self.assertEqual(hook.forked_from(["claude", "--fork-session", "--resume", "/p/abc.jsonl"]), "abc")
        self.assertEqual(hook.forked_from(["claude", "--resume=abc", "--fork-session"]), "abc")
        self.assertEqual(hook.forked_from(["claude", "--resume", "abc"]), "")
        self.assertEqual(hook.forked_from([]), "")

    def test_versioned_binary_counts_as_claude(self):
        self.assertTrue(hook.is_claude("2.1.319"))
        self.assertFalse(hook.is_claude("bash"))

    def test_hook_ancestors_start_at_pid(self):
        self.assertEqual(hook.ancestors(os.getpid())[:2], [os.getpid(), os.getppid()])

    def test_job_of_matches_background_pid(self):
        agents = [{"pid": 5, "id": "aaaa", "kind": "interactive"}, {"pid": 5, "id": "bbbb", "kind": "background"}]
        self.assertEqual(focus.job_of(agents, 5)["id"], "bbbb")
        self.assertIsNone(focus.job_of(agents, 6))

    def test_attach_command_prefers_override_then_wrapper(self):
        with tempfile.TemporaryDirectory() as bin_dir:
            wrapper = os.path.join(bin_dir, "claude-hl")
            pathlib.Path(wrapper).write_text("#!/bin/sh\n")
            os.chmod(wrapper, 0o755)
            self.assertEqual(focus.attach_command("/bin/claude", {"PATH": bin_dir}), wrapper)
            self.assertEqual(focus.attach_command("/bin/claude", {"PATH": bin_dir, "CLAUDE_SESSIONS_CLAUDE": "my-claude"}), "my-claude")
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(focus.attach_command("/bin/claude", {"PATH": empty}), "/bin/claude")

    def test_client_pids_skip_daemon_and_job_hosts(self):
        procs = [(1, ["/bin/claude"]), (2, ["/bin/claude", "daemon", "run"]), (3, ["claude", "bg-pty-host"]),
                 (4, ["claude", "attach", "x"]), (5, ["/v/2.1.319", "--session-id", "x"]), (6, [])]
        self.assertEqual(focus.client_pids(procs), [1, 4])

    def test_job_on_screen_in_agent_view_is_focused(self):
        agents = [{"pid": 77, "id": "job1", "kind": "background", "name": "fix-things"}]
        windows = [{"id": 3, "pid": 601, "title": "◐ other-job"}, {"id": 4, "pid": 701, "title": "◐ fix-things"}]
        runner = JobRunner(agents, windows)
        with self.job_env(procs=[(600, ["/bin/claude"]), (700, ["/bin/claude"])]):
            self.assertEqual(focus.focus({"pid": 77}, runner), "focused")
        self.assertEqual(runner.focused, 4)
        self.assertIsNone(runner.attached)

    def test_agent_view_on_another_job_gets_a_new_attach(self):
        agents = [{"pid": 77, "id": "job1", "kind": "background", "name": "fix-things"}]
        runner = JobRunner(agents, [{"id": 3, "pid": 601, "title": "◐ other-job"}])
        with self.job_env(procs=[(600, ["/bin/claude"])]):
            self.assertEqual(focus.focus({"pid": 77}, runner), "spawned")

    def test_attach_pids_need_the_job_id(self):
        procs = [(1, ["claude", "attach", "abc"]), (2, ["claude", "attach", "abcd"]), (3, ["claude", "attach"])]
        self.assertEqual(focus.attach_pids("abc", procs), [1])

    def test_background_job_opens_attach_terminal(self):
        runner = JobRunner([{"pid": 77, "id": "job1", "kind": "background"}], [])
        with self.job_env():
            self.assertEqual(focus.focus({"pid": 77}, runner), "spawned")
        self.assertEqual(runner.attached[:3], ("/bin/claude", "job1", "/w"))
        self.assertEqual(runner.attached[3]["CLAUDE_CONFIG_DIR"], "/cfg")

    def test_background_job_focuses_existing_attach(self):
        runner = JobRunner([{"pid": 77, "id": "job1", "kind": "background"}], [{"id": 4, "pid": 501}])
        with self.job_env(procs=[(500, ["claude", "attach", "job1"])]):
            self.assertEqual(focus.focus({"pid": 77}, runner), "focused")
        self.assertEqual(runner.focused, 4)
        self.assertIsNone(runner.attached)

    def job_env(self, procs=()):
        env = {"CLAUDE_CODE_SESSION_KIND": "bg", "PWD": "/w", "CLAUDE_CONFIG_DIR": "/cfg"}
        stack = contextlib.ExitStack()
        stack.enter_context(unittest.mock.patch.object(focus, "environ", lambda pid: env))
        stack.enter_context(unittest.mock.patch.object(focus, "claude_binary", lambda pid: "/bin/claude"))
        stack.enter_context(unittest.mock.patch.object(focus, "processes", lambda: list(procs)))
        stack.enter_context(unittest.mock.patch.object(focus, "ancestors", lambda pid: [pid, pid + 1]))
        return stack

    def test_ancestors_of_self(self):
        self.assertEqual(focus.ancestors(os.getpid())[:2], [os.getpid(), os.getppid()])


if __name__ == "__main__":
    unittest.main()
