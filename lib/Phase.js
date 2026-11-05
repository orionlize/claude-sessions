.pragma library

// How a session phase looks, shared by the popup rows and the switcher.

function color(theme, phase) {
    if (phase === "waiting")
        return theme.warning;
    if (phase === "tool")
        return theme.tertiary;
    if (phase === "thinking" || phase === "compacting")
        return theme.primary;
    if (phase === "error")
        return theme.error;
    return theme.surfaceVariantText;
}

// Untranslated; callers pass it through tr().
function label(phase) {
    return {
        waiting: "Waiting",
        tool: "Calling tool",
        thinking: "Thinking",
        compacting: "Compacting",
        error: "Error"
    }[phase] || "Idle";
}

function icon(phase) {
    return {
        waiting: "front_hand",
        tool: "build",
        thinking: "psychology",
        compacting: "compress",
        error: "error"
    }[phase] || "smart_toy";
}

// What a session is called in lists: its terminal's title, else its folder.
function name(session) {
    return (session && (session.termTitle || session.project)) || "";
}

function detail(session) {
    if (session.status === "error")
        return session.activity || "";
    if (session.phase === "idle" || session.phase === "thinking" || session.phase === "compacting")
        return session.title || session.prompt || "";
    if (session.activityKey === "tool")
        return session.tool + ": " + session.activity;
    return session.activity || "";
}
