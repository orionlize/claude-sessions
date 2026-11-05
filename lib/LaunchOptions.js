.pragma library

// Model and effort choices for the quick-launch box. "default" model passes no
// --model flag, so Claude Code uses whatever the user's own settings pick.

var DEFAULT_MODEL = "default";
var DEFAULT_EFFORT = "medium";
var MODELS = ["default", "fable", "opus", "sonnet", "haiku"];
var EFFORTS = ["low", "medium", "high", "xhigh", "max"];

// Built-in aliases, then any extra names from settings ("a, b" or one per line).
function models(extra) {
    var list = MODELS.slice();
    String(extra || "").split(/[\s,]+/).forEach(function (name) {
        if (name && list.indexOf(name) < 0)
            list.push(name);
    });
    return list;
}

function pick(list, value, fallback) {
    return list.indexOf(value) >= 0 ? value : fallback;
}

function cycle(list, value, delta) {
    var count = list.length;
    if (!count)
        return value;
    var index = list.indexOf(value);
    if (index < 0)
        return list[0];
    return list[(index + delta + count) % count];
}
