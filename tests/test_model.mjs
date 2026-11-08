import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";
import assert from "node:assert/strict";

const source = readFileSync(new URL("../lib/SessionModel.js", import.meta.url), "utf8").replace(".pragma library", "");
const context = {};
vm.runInNewContext(source, context);
const M = context;
const plain = v => JSON.parse(JSON.stringify(v));
const base = { session_id: "s", cwd: "/home/u/proj", pid: 7 };
const ev = (event, extra = {}) => ({ ...base, event, ...extra });
const run = (...events) => {
    let state = M.emptyState(), dropped = [];
    events.forEach((e, i) => {
        const r = M.apply(state, e, i + 1);
        state = r.state;
        dropped = dropped.concat(plain(r.dropped));
    });
    return { state, dropped };
};
const perm = (id, tool = "Bash", fp = "f") => ev("PermissionRequest", { request_id: id, kind: "permission", tool_name: tool, fingerprint: fp });
const status = state => M.sessionList(state)[0].status;

test("prompt then stop moves running to idle", () => {
    assert.equal(status(run(ev("SessionStart"), ev("UserPromptSubmit")).state), "running");
    assert.equal(status(run(ev("UserPromptSubmit"), ev("Stop")).state), "idle");
});

test("post tool use clears only the matching request", () => {
    const { state, dropped } = run(perm("a", "Bash", "1"), perm("b", "Bash", "2"), ev("PostToolUse", { tool_name: "Bash", fingerprint: "1" }));
    assert.deepEqual(dropped, ["a"]);
    assert.equal(state.requests.length, 1);
    assert.equal(status(state), "waiting");
});

test("answered question clears despite changed fingerprint", () => {
    const q = ev("PermissionRequest", { request_id: "q", kind: "question", tool_name: "AskUserQuestion", fingerprint: "x" });
    const { dropped } = run(q, ev("PostToolUse", { tool_name: "AskUserQuestion", fingerprint: "y" }));
    assert.deepEqual(dropped, ["q"]);
});

test("pending request outranks a parallel tool event", () => {
    assert.equal(status(run(perm("a"), ev("PreToolUse", { tool_name: "Read" })).state), "waiting");
});

test("stop, new prompt and session end all release requests", () => {
    for (const name of ["Stop", "UserPromptSubmit", "SessionEnd", "StopFailure"])
        assert.deepEqual(run(perm("a"), ev(name)).dropped, ["a"]);
});

test("resolve deny stops the turn, allow keeps it running", () => {
    const { state } = run(perm("a"));
    assert.equal(status(M.resolve(state, "a", "deny", 9)), "idle");
    assert.equal(status(M.resolve(state, "a", "allow", 9)), "running");
    const q = run(ev("PermissionRequest", { request_id: "q", kind: "question", tool_name: "AskUserQuestion" })).state;
    assert.equal(status(M.resolve(q, "q", "deny", 9)), "running");
});

test("sweep removes dead sessions with their requests", () => {
    const { state } = run(perm("a"));
    const r = M.applySweep(state, { alive: { s: false }, interrupted: {} });
    assert.deepEqual(plain(r.dropped), ["a"]);
    assert.equal(Object.keys(r.state.sessions).length, 0);
});

test("sweep honours only interrupts newer than the last event", () => {
    const { state } = run(ev("UserPromptSubmit"));
    assert.equal(status(M.applySweep(state, { alive: { s: true }, interrupted: { s: 0.5 } }).state), "running");
    assert.equal(status(M.applySweep(state, { alive: { s: true }, interrupted: { s: 5 } }).state), "idle");
});

test("sweep keeps the terminal title and clears it when gone", () => {
    const { state } = run(ev("UserPromptSubmit"));
    const titled = M.applySweep(state, { alive: { s: true }, interrupted: {}, titles: { s: "fix bar" } }).state;
    assert.equal(titled.sessions.s.termTitle, "fix bar");
    assert.equal(M.applySweep(titled, { alive: { s: true }, interrupted: {} }).state.sessions.s.termTitle, "fix bar");
    assert.equal(M.applySweep(titled, { alive: { s: true }, interrupted: {}, titles: {} }).state.sessions.s.termTitle, "");
});

test("interrupted permission prompt is released", () => {
    const { state } = run(perm("a"));
    const r = M.applySweep(state, { alive: { s: true }, interrupted: { s: 5 } });
    assert.deepEqual(plain(r.dropped), ["a"]);
    assert.equal(status(r.state), "idle");
});

test("notification waits only without a real request", () => {
    const n = ev("Notification", { notification_type: "permission_prompt", message: "m" });
    assert.equal(run(ev("UserPromptSubmit"), n).state.sessions.s.activityKey, "attention");
    assert.equal(run(perm("a"), n).state.sessions.s.activityKey, "tool");
});

test("auto compaction stays running, manual settles", () => {
    assert.equal(status(run(ev("UserPromptSubmit"), ev("PreCompact"), ev("PostCompact", { trigger: "auto" })).state), "running");
    assert.equal(status(run(ev("PreCompact"), ev("PostCompact", { trigger: "manual" })).state), "idle");
});

test("list puts waiting before running before idle", () => {
    let state = M.emptyState();
    state = M.apply(state, { ...ev("Stop"), session_id: "i" }, 1).state;
    state = M.apply(state, { ...ev("UserPromptSubmit"), session_id: "r" }, 2).state;
    state = M.apply(state, { ...perm("a"), session_id: "w" }, 3).state;
    assert.deepEqual(plain(M.sessionList(state).map(s => s.id)), ["w", "r", "i"]);
});

test("restore drops waiting because the prompt socket is gone", () => {
    const saved = run(perm("a")).state.sessions;
    const restored = M.restore(plain(saved));
    assert.equal(status(restored), "running");
    assert.equal(restored.requests.length, 0);
});

const pre = (id, tool = "Bash", extra = {}) => ev("PreToolUse", { tool_use_id: id, tool_name: tool, fingerprint: id, activity: tool + " run", ...extra });
const post = id => ev("PostToolUse", { tool_use_id: id, tool_name: "Bash", fingerprint: id });
const phase = state => M.sessionList(state)[0].phase;

test("phase follows thinking, tool and idle", () => {
    assert.equal(phase(run(ev("UserPromptSubmit")).state), "thinking");
    assert.equal(phase(run(ev("UserPromptSubmit"), pre("a")).state), "tool");
    assert.equal(phase(run(ev("UserPromptSubmit"), pre("a"), post("a")).state), "thinking");
    assert.equal(phase(run(ev("UserPromptSubmit"), ev("PreCompact")).state), "compacting");
    assert.equal(phase(run(ev("UserPromptSubmit"), pre("a"), ev("Stop")).state), "idle");
    assert.equal(phase(run(perm("a")).state), "waiting");
});

test("parallel tools stay in the tool phase until the last one ends", () => {
    const { state } = run(pre("a", "Bash"), pre("b", "Read"), post("b"));
    const session = M.sessionList(state)[0];
    assert.equal(session.phase, "tool");
    assert.equal(session.tool, "Bash");
    assert.equal(session.activity, "Bash run");
    assert.equal(phase(M.apply(state, post("a"), 9).state), "thinking");
});

test("approved tool shows as running, not thinking", () => {
    const pending = ev("PermissionRequest", { request_id: "r", kind: "permission", tool_name: "Bash", fingerprint: "a" });
    const { state } = run(pre("a"), pending);
    const resolved = M.resolve(state, "r", "allow", 9);
    assert.equal(phase(resolved), "tool");
    assert.equal(phase(M.apply(resolved, post("a"), 10).state), "thinking");
});

test("declined question goes back to thinking", () => {
    const q = ev("PermissionRequest", { request_id: "q", kind: "question", tool_name: "AskUserQuestion", fingerprint: "a" });
    const { state } = run(pre("a", "AskUserQuestion"), q);
    assert.equal(phase(M.resolve(state, "q", "deny", 9)), "thinking");
});

test("auto compaction returns to the previous phase", () => {
    assert.equal(phase(run(ev("UserPromptSubmit"), ev("PreCompact"), ev("PostCompact", { trigger: "auto" })).state), "thinking");
});

test("late events do not revive an idle session", () => {
    assert.equal(status(run(ev("UserPromptSubmit"), pre("a"), ev("Stop"), post("a")).state), "idle");
    assert.equal(status(run(ev("Stop"), pre("a", "Read", { is_subagent: true })).state), "idle");
});

test("a new prompt forgets tools that never finished", () => {
    assert.equal(phase(run(pre("a"), ev("UserPromptSubmit")).state), "thinking");
});

test("state saved before tool tracking still restores", () => {
    const restored = M.restore({ s: { id: "s", status: "waiting", lastEventAt: 1 } });
    assert.equal(phase(restored), "thinking");
});

test("tmux location is kept for jumping to the session", () => {
    const { state } = run(ev("SessionStart", { tmux: "/tmp/t,1,0", tmux_pane: "%4" }), ev("Stop"));
    const session = M.sessionList(state)[0];
    assert.equal(session.tmux, "/tmp/t,1,0");
    assert.equal(session.tmuxPane, "%4");
});

test("filter matches every word and ranks project hits first", () => {
    const list = [
        { project: "notes", title: "fix widget popup", cwd: "/a/notes" },
        { project: "claude-widget", title: "spotlight", cwd: "/a/claude-widget" },
        { project: "widget", title: "", cwd: "/a/widget" },
    ];
    const names = q => plain(M.filterSessions(list, q)).map(s => s.project);
    assert.deepEqual(names(""), ["notes", "claude-widget", "widget"]);
    assert.deepEqual(names("widget"), ["widget", "claude-widget", "notes"]);
    assert.deepEqual(names("WIDGET popup"), ["notes"]);
    assert.deepEqual(names("nothing"), []);
});

test("focus command carries the tmux location", () => {
    assert.equal(M.focusCommand("/p", { pid: 0 }), null);
    const argv = plain(M.focusCommand("/p", { pid: 5, tmux: "/t,1,0", tmuxPane: "%2" }));
    assert.equal(argv[2], "/p/scripts/focus.py");
    assert.deepEqual(JSON.parse(argv[3]), { pid: 5, tmux: "/t,1,0", pane: "%2" });
});

test("a session nobody has used yet stays hidden", () => {
    const visible = (...events) => M.sessionList(run(...events).state).length;
    assert.equal(visible(ev("SessionStart", { source: "startup" })), 0);
    assert.equal(visible(ev("SessionStart"), ev("Notification", { notification_type: "idle_prompt" })), 0);
    assert.equal(visible(ev("SessionStart"), ev("UserPromptSubmit")), 1);
    assert.equal(visible(ev("SessionStart", { source: "resume" })), 1);
    assert.equal(visible(ev("SessionStart", { source: "clear" })), 1);
    assert.equal(visible(ev("Stop")), 1);
    assert.equal(Object.keys(run(ev("SessionStart")).state.sessions).length, 1);
});

test("restore hides unused sessions saved before pristine tracking", () => {
    const restored = M.restore({
        e: { id: "e", status: "idle", prompt: "", lastEventAt: 1 },
        u: { id: "u", status: "idle", prompt: "hi", lastEventAt: 2 },
    });
    assert.deepEqual(plain(M.sessionList(restored).map(s => s.id)), ["u"]);
});

test("a dashboard reply lists only the background fork", () => {
    const viewer = { session_id: "job", pid: 10 };
    const fork = { session_id: "fork", pid: 30, forked_from: "job", ancestors: [30, 20, 10, 5] };
    const { state } = run(
        ev("SessionStart", { ...viewer, source: "resume" }),
        ev("UserPromptSubmit", { ...viewer, prompt: "again" }),
        ev("SessionStart", { ...fork, source: "resume" }),
        ev("PreToolUse", { ...fork, tool_use_id: "a", tool_name: "Bash" }),
    );
    const list = plain(M.sessionList(state));
    assert.deepEqual(list.map(s => s.id), ["fork"]);
    assert.equal(list[0].prompt, "again");
    // Opening the job again in its own process brings it back.
    assert.equal(M.sessionList(M.apply(state, ev("SessionStart", { ...viewer, source: "resume" }), 9).state).length, 2);
});

test("a fork in another window keeps its parent listed", () => {
    const { state } = run(
        ev("UserPromptSubmit", { session_id: "job", pid: 10 }),
        ev("UserPromptSubmit", { session_id: "fork", pid: 30, forked_from: "job", ancestors: [30, 20] }),
    );
    assert.equal(M.sessionList(state).length, 2);
});
