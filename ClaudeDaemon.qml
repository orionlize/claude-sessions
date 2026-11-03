import QtQuick
import Quickshell
import Quickshell.Io
import qs.Common
import qs.Services
import "./lib/SessionModel.js" as Model
import "./lib/Folders.js" as Folders
import "./components"

// Owns all state. It runs once per shell, whereas the bar widget has one instance
// per bar, and it never adds itself to a bar: the user does that in Settings.
Item {
    id: root

    property var pluginService: null
    property string pluginId: ""
    property var model: Model.emptyState()
    property var waitingSockets: ({})
    property bool sweepRunning: false
    // Folders started from quick launch, newest first; "" in lastFolder means a temp folder.
    property var launchedFolders: []
    property string lastFolder: ""
    property string pendingFolder: ""

    readonly property string socketPath: {
        const runtime = Quickshell.env("XDG_RUNTIME_DIR");
        return runtime ? runtime + "/claude-sessions.sock" : "";
    }
    readonly property bool hasSessions: Object.keys(model.sessions).length > 0
    readonly property bool hasBusySessions: Object.values(model.sessions).some(s => s.status !== "idle")

    function pluginDir() {
        const plugin = pluginService?.availablePlugins?.[pluginId];
        return plugin?.pluginDirectory ?? "";
    }

    function publish() {
        if (!pluginService || !pluginId)
            return;
        pluginService.setGlobalVar(pluginId, "sessions", Model.sessionList(model));
        pluginService.setGlobalVar(pluginId, "requests", model.requests);
        pluginService.savePluginState(pluginId, "sessions", model.sessions);
    }

    function restore() {
        if (!pluginService || !pluginId)
            return;
        model = Model.restore(pluginService.loadPluginState(pluginId, "sessions", {}));
        launchedFolders = pluginService.loadPluginState(pluginId, "launchedFolders", []) || [];
        lastFolder = pluginService.loadPluginState(pluginId, "lastFolder", "") || "";
        publish();
        sweep();
    }

    function reply(requestId, message) {
        const socket = waitingSockets[requestId];
        delete waitingSockets[requestId];
        if (!socket || !socket.connected)
            return;
        socket.write(JSON.stringify(message) + "\n");
        socket.flush();
    }

    // The terminal may answer first, and Claude leaves our hook running when it does.
    function release(requestIds) {
        requestIds.forEach(id => reply(id, {
            action: "pass"
        }));
    }

    function takeResult(result) {
        model = result.state;
        release(result.dropped);
        publish();
    }

    function handleLine(socket, line) {
        let event;
        try {
            event = JSON.parse(line);
        } catch (e) {
            return;
        }
        if (event.request_id) {
            socket.requestId = event.request_id;
            waitingSockets[event.request_id] = socket;
        }
        takeResult(Model.apply(model, event, Date.now()));
    }

    function handleDisconnect(socket) {
        const id = socket.requestId;
        if (!id || !waitingSockets[id])
            return;
        delete waitingSockets[id];
        model = Model.removeRequest(model, id);
        publish();
    }

    function handleDecision(decision) {
        if (!decision?.id || !waitingSockets[decision.id])
            return;
        reply(decision.id, {
            action: decision.action,
            answers: decision.answers
        });
        model = Model.resolve(model, decision.id, decision.action, Date.now());
        publish();
    }

    function focusSession(session) {
        const command = Model.focusCommand(pluginDir(), session);
        if (command)
            Quickshell.execDetached(command);
    }

    // An empty folder starts the session in its own new /tmp/<uuid> directory.
    function launch(prompt, folder) {
        if (!pluginDir() || launchProcess.running)
            return;
        pendingFolder = folder;
        launchProcess.command = ["python3", "-S", pluginDir() + "/scripts/launch.py", JSON.stringify({
                cwd: folder,
                prompt: prompt
            })];
        launchProcess.running = true;
    }

    // Like Desktop, the next launch starts in the folder that last worked.
    function rememberFolder(folder) {
        lastFolder = folder;
        launchedFolders = Folders.remember(launchedFolders, folder);
        if (!pluginService || !pluginId)
            return;
        pluginService.savePluginState(pluginId, "lastFolder", lastFolder);
        pluginService.savePluginState(pluginId, "launchedFolders", launchedFolders);
    }

    function toggleLaunch(): string {
        closeSwitchers();
        if (!quickLaunch.shown)
            quickLaunch.folder = lastFolder;
        quickLaunch.toggle();
        return quickLaunch.shown ? "opened" : "closed";
    }

    function sweep() {
        if (sweepRunning || !hasSessions || !pluginDir())
            return;
        const targets = Object.values(model.sessions).map(s => ({
            id: s.id,
            pid: s.pid,
            transcript: s.transcript
        }));
        sweepProcess.command = ["python3", "-S", pluginDir() + "/scripts/sweep.py", JSON.stringify(targets)];
        sweepRunning = true;
        sweepProcess.running = true;
    }

    onPluginServiceChanged: restore()
    onPluginIdChanged: restore()

    Connections {
        target: root.pluginService
        function onGlobalVarChanged(changedPluginId, varName) {
            if (changedPluginId === root.pluginId && varName === "decision")
                root.handleDecision(root.pluginService.getGlobalVar(root.pluginId, "decision", null));
        }
    }

    // "spotlight" (search pill) or "tiles" (grid with previews), chosen in settings.
    function switcherFor(mode) {
        const chosen = mode || SettingsData.getPluginSettingsForPlugin(pluginId)?.switcherMode || "spotlight";
        return chosen === "tiles" ? tileSwitcher : switcher;
    }

    function toggleSwitcher(mode) {
        const target = switcherFor(mode);
        const other = target === tileSwitcher ? switcher : tileSwitcher;
        quickLaunch.close();
        if (other.shown)
            other.close();
        // The compositor still sees Mod+Tab while the tiles are up: step through them
        // like Alt-Tab; releasing Mod picks one.
        if (target === tileSwitcher && target.shown) {
            target.move(1);
            return "next";
        }
        target.toggle();
        return target.shown ? "opened" : "closed";
    }

    function closeSwitchers() {
        switcher.close();
        tileSwitcher.close();
    }

    QuickLaunch {
        id: quickLaunch

        pluginDir: root.pluginDir()
        recentFolders: Folders.recentFolders(root.launchedFolders, Model.sessionList(root.model))
        onSubmitted: (prompt, folder) => root.launch(prompt, folder)
    }

    Process {
        id: launchProcess

        onExited: exitCode => {
            if (exitCode === 0)
                root.rememberFolder(root.pendingFolder);
        }

        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim())
                    ToastService.showError("Claude: " + text.trim());
            }
        }
    }

    SessionSwitcher {
        id: switcher

        sessions: Model.sessionList(root.model)
        onActivated: session => root.focusSession(session)
    }

    TileSwitcher {
        id: tileSwitcher

        sessions: Model.sessionList(root.model)
        pluginDir: root.pluginDir()
        onActivated: session => root.focusSession(session)
    }

    // Bound to a key in the compositor: dms ipc call claudeSessions toggle
    IpcHandler {
        target: "claudeSessions"

        // Uses the mode chosen in settings.
        function toggle(): string {
            return root.toggleSwitcher("");
        }

        function spotlight(): string {
            return root.toggleSwitcher("spotlight");
        }

        function tiles(): string {
            return root.toggleSwitcher("tiles");
        }

        function open(): string {
            const target = root.switcherFor("");
            if (!target.shown)
                root.toggleSwitcher("");
            return "opened";
        }

        // Quick entry box that starts a new session in a new terminal.
        function launch(): string {
            return root.toggleLaunch();
        }

        function close(): string {
            quickLaunch.close();
            root.closeSwitchers();
            return "closed";
        }
    }

    SocketServer {
        active: root.socketPath !== ""
        path: root.socketPath
        handler: Component {
            Socket {
                id: connection

                property string requestId: ""

                parser: SplitParser {
                    onRead: line => root.handleLine(connection, line)
                }
                onConnectedChanged: {
                    if (!connected)
                        root.handleDisconnect(connection);
                }
            }
        }
    }

    // Esc in the terminal fires no hook, so busy sessions are checked more often.
    Timer {
        interval: root.hasBusySessions ? 2000 : 15000
        repeat: true
        running: root.hasSessions
        onTriggered: root.sweep()
    }

    Process {
        id: sweepProcess

        stdout: StdioCollector {
            id: sweepOutput
        }
        onExited: exitCode => {
            root.sweepRunning = false;
            if (exitCode !== 0)
                return;
            try {
                root.takeResult(Model.applySweep(root.model, JSON.parse(sweepOutput.text)));
            } catch (e) {
                console.warn("claudeSessions: bad sweep output:", e);
            }
        }
    }
}
