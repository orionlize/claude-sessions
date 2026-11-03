.pragma library

// Pure session state. `state` is {sessions: {id: session}, requests: [request]}.
// Each function returns {state, dropped}; dropped lists request ids whose hook
// process should be released.

var STATUS_RANK = { waiting: 0, running: 1, error: 2, idle: 3 };

function emptyState() {
    return { sessions: {}, requests: [] };
}

function projectName(cwd) {
    var parts = String(cwd || "").split("/").filter(function (p) { return p.length > 0; });
    return parts.length ? parts[parts.length - 1] : "~";
}

function upsert(sessions, ev, now) {
    var previous = sessions[ev.session_id];
    var session = Object.assign({
        id: ev.session_id,
        project: projectName(ev.cwd),
        status: "idle",
        activity: "",
        activityKey: "",
        tools: [],
        prompt: "",
        title: "",
        startedAt: now
    }, previous || {});
    session.lastEventAt = now;
    if (ev.cwd) {
        session.cwd = ev.cwd;
        session.project = projectName(ev.cwd);
    }
    if (ev.pid)
        session.pid = ev.pid;
    if (ev.tmux_pane) {
        session.tmux = ev.tmux;
        session.tmuxPane = ev.tmux_pane;
    }
    if (ev.transcript_path)
        session.transcript = ev.transcript_path;
    if (ev.title)
        session.title = ev.title;
    if (ev.permission_mode)
        session.permissionMode = ev.permission_mode;
    return session;
}

function setActivity(session, status, activity, activityKey) {
    session.status = status;
    session.activity = activity || "";
    session.activityKey = activityKey || "";
    if (status === "idle" || status === "error")
        session.tools = [];
}

// PermissionRequest carries no tool_use_id, so requests match by fingerprint.
function removeTool(session, toolUseId, fingerprint) {
    var removed = false;
    session.tools = (session.tools || []).filter(function (t) {
        var match = toolUseId ? t.id === toolUseId : t.fingerprint === fingerprint;
        if (removed || !match)
            return true;
        removed = true;
        return false;
    });
}

// Claude is between tools only once nothing is in flight: parallel calls and
// subagents overlap, and an approved tool starts without a new PreToolUse.
function resumeRunning(session) {
    var tools = session.tools || [];
    var latest = tools[tools.length - 1];
    if (latest) {
        setActivity(session, "running", latest.activity, "tool");
        session.tool = latest.name;
    } else {
        setActivity(session, "running", "", "thinking");
    }
}

function partition(requests, shouldDrop) {
    var kept = [], dropped = [];
    requests.forEach(function (r) {
        if (shouldDrop(r))
            dropped.push(r.id);
        else
            kept.push(r);
    });
    return { kept: kept, dropped: dropped };
}

function matchesTool(request, ev) {
    if (request.session_id !== ev.session_id || request.tool_name !== ev.tool_name)
        return false;
    // Answering a question rewrites its input, so its fingerprint cannot match.
    return request.kind === "question" || request.fingerprint === ev.fingerprint;
}

function makeRequest(ev, now) {
    return {
        id: ev.request_id,
        session_id: ev.session_id,
        kind: ev.kind,
        tool_name: ev.tool_name || "",
        fingerprint: ev.fingerprint || "",
        detail: ev.detail || "",
        always_label: ev.always_label || "",
        questions: ev.questions || [],
        project: projectName(ev.cwd),
        createdAt: now
    };
}

function apply(state, ev, now) {
    if (!ev || !ev.session_id)
        return { state: state, dropped: [] };

    var sessions = Object.assign({}, state.sessions);
    var requests = state.requests;
    var session = upsert(sessions, ev, now);
    var ofSession = function (r) { return r.session_id === ev.session_id; };
    var drop = null;

    switch (ev.event) {
    case "SessionStart":
        if (ev.source !== "compact" && session.status !== "running")
            setActivity(session, "idle");
        break;
    case "SessionEnd":
        delete sessions[ev.session_id];
        session = null;
        drop = ofSession;
        break;
    case "UserPromptSubmit":
        setActivity(session, "running", "", "thinking");
        session.tools = [];
        session.prompt = ev.prompt || "";
        drop = ofSession;
        break;
    case "PreToolUse":
        // A background subagent outlives the turn and gets no Stop of its own.
        if (ev.is_subagent && session.status === "idle")
            break;
        session.tools = (session.tools || []).concat([{
            id: ev.tool_use_id || "",
            fingerprint: ev.fingerprint || "",
            name: ev.tool_name || "",
            activity: ev.activity || ""
        }]);
        setActivity(session, "running", ev.activity, "tool");
        session.tool = ev.tool_name || "";
        break;
    case "PostToolUse":
    case "PostToolUseFailure":
    case "PermissionDenied":
        removeTool(session, ev.tool_use_id, ev.fingerprint);
        if (session.status !== "idle" && session.status !== "error")
            resumeRunning(session);
        drop = function (r) { return matchesTool(r, ev); };
        break;
    case "PermissionRequest":
        setActivity(session, "waiting", ev.activity, "tool");
        session.tool = ev.tool_name || "";
        requests = requests.concat([makeRequest(ev, now)]);
        break;
    case "Notification":
        if (ev.notification_type === "permission_prompt" || ev.notification_type === "elicitation_dialog") {
            if (!requests.some(ofSession))
                setActivity(session, "waiting", ev.message, "attention");
        } else if (ev.notification_type === "idle_prompt") {
            setActivity(session, "idle");
        }
        break;
    case "Stop":
        setActivity(session, "idle");
        drop = ofSession;
        break;
    case "StopFailure":
        setActivity(session, "error", ev.message, "error");
        drop = ofSession;
        break;
    case "PreCompact":
        setActivity(session, "running", "", "compacting");
        break;
    case "PostCompact":
        if (ev.trigger === "manual")
            setActivity(session, "idle");
        else
            resumeRunning(session);
        break;
    }

    if (session)
        sessions[ev.session_id] = session;

    var parts = drop ? partition(requests, drop) : { kept: requests, dropped: [] };
    return { state: { sessions: sessions, requests: parts.kept }, dropped: parts.dropped };
}

// The widget answered request `id`.
function resolve(state, id, action, now) {
    var request = state.requests.filter(function (r) { return r.id === id; })[0];
    if (!request)
        return state;
    var requests = state.requests.filter(function (r) { return r.id !== id; });
    var sessions = Object.assign({}, state.sessions);
    var existing = sessions[request.session_id];
    if (existing) {
        var session = Object.assign({}, existing, { lastEventAt: now });
        // A denied tool interrupts the turn, and Claude fires no Stop for that.
        if (action === "deny" && request.kind === "permission")
            setActivity(session, "idle");
        else {
            if (action === "deny")
                removeTool(session, "", request.fingerprint);
            resumeRunning(session);
        }
        sessions[request.session_id] = session;
    }
    return { sessions: sessions, requests: requests };
}

// A hook process went away without an answer.
function removeRequest(state, id) {
    return {
        sessions: state.sessions,
        requests: state.requests.filter(function (r) { return r.id !== id; })
    };
}

function applySweep(state, report) {
    var sessions = Object.assign({}, state.sessions);
    var gone = {};
    Object.keys(sessions).forEach(function (id) {
        var session = sessions[id];
        if (report.alive && report.alive[id] === false) {
            delete sessions[id];
            gone[id] = true;
            return;
        }
        var at = report.interrupted ? report.interrupted[id] : 0;
        var busy = session.status === "running" || session.status === "waiting";
        if (at && at >= session.lastEventAt && busy) {
            var next = Object.assign({}, session);
            setActivity(next, "idle");
            sessions[id] = next;
            gone[id] = true;
        }
    });
    var parts = partition(state.requests, function (r) { return gone[r.session_id] === true; });
    return { state: { sessions: sessions, requests: parts.kept }, dropped: parts.dropped };
}

function phaseOf(session) {
    if (session.status !== "running")
        return session.status;
    return session.activityKey === "tool" || session.activityKey === "compacting" ? session.activityKey : "thinking";
}

// Pending requests outrank whatever the last event said.
function sessionList(state) {
    var pending = {};
    state.requests.forEach(function (r) { pending[r.session_id] = true; });
    return Object.keys(state.sessions).map(function (id) {
        var session = Object.assign({}, state.sessions[id]);
        if (pending[id])
            session.status = "waiting";
        session.phase = phaseOf(session);
        return session;
    }).sort(function (a, b) {
        var rank = STATUS_RANK[a.status] - STATUS_RANK[b.status];
        return rank !== 0 ? rank : b.lastEventAt - a.lastEventAt;
    });
}

function restore(saved) {
    var sessions = {};
    Object.keys(saved || {}).forEach(function (id) {
        // A pending prompt did not survive the restart: its socket is gone.
        var session = Object.assign({}, saved[id]);
        if (session.status === "waiting")
            resumeRunning(session);
        sessions[id] = session;
    });
    return { sessions: sessions, requests: [] };
}

// Every space-separated word must appear in the session's project, title, prompt,
// activity or path. A project match ranks first; otherwise the list keeps its order.
function filterSessions(list, query) {
    var words = String(query || "").toLowerCase().split(/\s+/).filter(function (w) { return w.length > 0; });
    if (!words.length)
        return list.slice();
    var hits = [];
    list.forEach(function (session, index) {
        var project = String(session.project || "").toLowerCase();
        var haystack = [project, session.title, session.prompt, session.activity, session.tool, session.cwd]
            .map(function (v) { return String(v || "").toLowerCase(); }).join("\n");
        if (!words.every(function (w) { return haystack.indexOf(w) >= 0; }))
            return;
        var rank = project.indexOf(words[0]) === 0 ? 0 : project.indexOf(words[0]) > 0 ? 1 : 2;
        hits.push({ session: session, rank: rank, index: index });
    });
    hits.sort(function (a, b) { return a.rank - b.rank || a.index - b.index; });
    return hits.map(function (h) { return h.session; });
}

// argv that brings `session` to the front; null when it cannot be located.
function focusCommand(pluginDir, session) {
    if (!pluginDir || !session || !session.pid)
        return null;
    return ["python3", "-S", pluginDir + "/scripts/focus.py", JSON.stringify({
        pid: session.pid,
        tmux: session.tmux || "",
        pane: session.tmuxPane || ""
    })];
}
