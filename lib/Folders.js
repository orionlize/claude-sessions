.pragma library

// Working-folder choices for the quick-launch box. A folder of "" means a new
// /tmp/<uuid> directory, made fresh for each launch.

var MAX_RECENT = 8;
var MAX_ITEMS = 12;
var SCRATCH = /^\/tmp\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/?$/;

function clean(path) {
    path = String(path || "").trim();
    return path.length > 1 ? path.replace(/\/+$/, "") : path;
}

// Scratch folders from earlier quick launches are not worth offering again.
function isScratch(path) {
    return SCRATCH.test(String(path || ""));
}

function expand(path, home) {
    path = clean(path);
    if (home && (path === "~" || path.indexOf("~/") === 0))
        return clean(home + path.slice(1));
    return path;
}

function shorten(path, home) {
    path = clean(path);
    home = clean(home);
    if (home && home !== "/" && (path === home || path.indexOf(home + "/") === 0))
        return "~" + path.slice(home.length);
    return path;
}

function folderName(path) {
    var parts = clean(path).split("/").filter(function (p) { return p.length > 0; });
    return parts.length ? parts[parts.length - 1] : "/";
}

function remember(recent, path) {
    path = clean(path);
    var list = (recent || []).filter(function (p) { return clean(p) !== path; });
    if (path && !isScratch(path))
        list.unshift(path);
    return list.slice(0, MAX_RECENT);
}

// Folders launched from here come first, then folders of live sessions, newest first.
function recentFolders(recent, sessions) {
    var seen = {};
    var out = [];
    function add(path) {
        path = clean(path);
        if (!path || seen[path] || isScratch(path))
            return;
        seen[path] = true;
        out.push(path);
    }
    (recent || []).forEach(add);
    (sessions || []).slice().sort(function (a, b) {
        return (b.lastEventAt || 0) - (a.lastEventAt || 0);
    }).forEach(function (s) { add(s.cwd); });
    return out;
}

function looksLikePath(query) {
    query = String(query || "");
    return query.charAt(0) === "/" || query.charAt(0) === "~";
}

// Rows for the picker: {path} with "" for a new temporary folder. A typed path
// lists the matching directories on disk (`completions`) before recent ones.
function items(recent, completions, query, home) {
    query = String(query || "").trim();
    var seen = {};
    var out = [];
    function add(path) {
        path = clean(path);
        if (seen[path] === true)
            return;
        seen[path] = true;
        out.push({ path: path });
    }
    if (!query)
        add("");
    if (looksLikePath(query))
        (completions || []).forEach(add);
    var needle = query.toLowerCase();
    var expanded = expand(query, home).toLowerCase();
    (recent || []).forEach(function (path) {
        var hay = (path + "\n" + shorten(path, home)).toLowerCase();
        if (!needle || hay.indexOf(needle) >= 0 || hay.indexOf(expanded) >= 0)
            add(path);
    });
    return out.slice(0, MAX_ITEMS);
}
