import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Common
import qs.Services
import qs.Modules.Plugins
import qs.Widgets
import qs.DCommon.Widgets
import "./components"
import "./lib/SessionModel.js" as Model
import "./lib/Phase.js" as Phase

PluginComponent {
    id: root

    layerNamespacePlugin: "claude-sessions"

    PluginGlobalVar {
        id: sessionsVar
        varName: "sessions"
        defaultValue: []
    }

    PluginGlobalVar {
        id: requestsVar
        varName: "requests"
        defaultValue: []
    }

    readonly property var sessions: sessionsVar.value || []
    readonly property var requests: requestsVar.value || []
    readonly property var primary: sessions.length ? sessions[0] : null
    readonly property string primaryPhase: primary ? primary.phase : "none"
    readonly property bool anyRunning: sessions.some(s => s.status === "running")
    readonly property bool anyWaiting: sessions.some(s => s.status === "waiting")
    readonly property bool animate: !SettingsData.reduceMotion && surfaceLive
    readonly property bool autoPopup: pluginData.autoPopup ?? true
    readonly property bool showLabel: pluginData.showLabel ?? true
    readonly property int maxDots: 6
    readonly property string newestRequestId: requests.length ? requests[requests.length - 1].id : ""
    readonly property bool onFocusedScreen: !parentScreen || parentScreen.name === CompositorService.getFocusedScreenName()

    property real breath: 1
    property string lastSeenRequestId: ""

    function tr(text) {
        return I18n.trFor("claudeSessions", text);
    }

    function phaseColor(phase) {
        return Phase.color(Theme, phase);
    }

    function dotOpacity(status) {
        if (status === "running" || status === "waiting")
            return root.breath;
        return status === "idle" ? 0.55 : 1;
    }

    readonly property color accent: anyWaiting ? Theme.warning : primaryPhase === "tool" || primaryPhase === "error" ? phaseColor(primaryPhase) : Theme.primary
    readonly property string labelText: {
        if (requests.length > 0)
            return requests.length > 1 ? tr("%1 waiting").arg(requests.length) : tr("Needs input");
        if (!primary || primary.status === "idle")
            return "";
        if (primaryPhase === "tool")
            return primary.project + " · " + primary.tool;
        if (primaryPhase === "thinking")
            return primary.project + " · " + tr("Thinking");
        if (primaryPhase === "compacting")
            return primary.project + " · " + tr("Compacting");
        return primary.project;
    }

    function setPopoutOpen(open) {
        pluginService?.setGlobalVar(pluginId, "popoutOpen", open);
    }

    function showPopout(automatic) {
        const anchor = pillAnchor();
        if (!anchor)
            return;
        claudePopout.open(anchor, automatic);
    }

    function claimAutoPopup() {
        const id = newestRequestId;
        if (!id || !pluginService)
            return;
        if (pluginService.getGlobalVar(pluginId, "claimedRequest", "") === id)
            return;
        pluginService.setGlobalVar(pluginId, "claimedRequest", id);
        if (!pluginService.getGlobalVar(pluginId, "popoutOpen", false))
            showPopout(true);
    }

    function submit(id, action, answers) {
        pluginService?.setGlobalVar(pluginId, "decision", {
            id: id,
            action: action,
            answers: answers
        });
    }

    // Close first so the popup hands the keyboard back before the terminal is focused.
    function focusSession(session) {
        const command = Model.focusCommand(pluginService?.availablePlugins?.[pluginId]?.pluginDirectory, session);
        if (!command)
            return;
        claudePopout.close();
        Quickshell.execDetached(command);
    }

    onNewestRequestIdChanged: {
        if (requests.length === 0) {
            if (claudePopout.automatic)
                claudePopout.close();
            return;
        }
        if (newestRequestId === lastSeenRequestId || !autoPopup)
            return;
        lastSeenRequestId = newestRequestId;
        // Prefer the bar under the user's focus; any other bar covers for a screen without one.
        claimTimer.interval = onFocusedScreen ? 1 : 250;
        claimTimer.restart();
    }

    Timer {
        id: claimTimer
        onTriggered: root.claimAutoPopup()
    }

    pillClickAction: () => {
        if (claudePopout.shown)
            claudePopout.close();
        else
            root.showPopout(false);
    }

    SequentialAnimation on breath {
        running: root.animate && (root.anyRunning || root.anyWaiting)
        loops: Animation.Infinite
        alwaysRunToEnd: false
        onRunningChanged: {
            if (!running)
                root.breath = 1;
        }

        NumberAnimation {
            to: 0.3
            duration: root.anyWaiting ? 450 : 1400
            easing.type: Easing.InOutSine
        }

        NumberAnimation {
            to: 1
            duration: root.anyWaiting ? 450 : 1400
            easing.type: Easing.InOutSine
        }
    }

    component BarIcon: ClaudeLogo {
        size: root.iconSize
        color: root.accent
        opacity: root.anyRunning || root.anyWaiting ? root.breath : root.sessions.length ? 1 : 0.5
        scale: root.anyRunning && !root.anyWaiting ? 0.92 + 0.08 * root.breath : 1
    }

    component SessionDot: Rectangle {
        required property var modelData

        width: Math.max(6, Math.round(root.iconSize * 0.3))
        height: width
        radius: width / 2
        color: root.phaseColor(modelData.phase)
        opacity: root.dotOpacity(modelData.status)
    }

    horizontalBarPill: Component {
        Row {
            spacing: Theme.spacingXS

            BarIcon {
                anchors.verticalCenter: parent.verticalCenter
            }

            Row {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 3
                visible: root.sessions.length > 0

                Repeater {
                    model: root.sessions.slice(0, root.maxDots)

                    SessionDot {}
                }
            }

            StyledText {
                anchors.verticalCenter: parent.verticalCenter
                visible: root.showLabel && text.length > 0
                text: root.labelText
                font.pixelSize: root.textSize
                color: Theme.widgetTextColor
                elide: Text.ElideRight
                wrapMode: Text.NoWrap
                width: Math.min(implicitWidth, 220)
            }
        }
    }

    verticalBarPill: Component {
        Column {
            spacing: Theme.spacingXS

            BarIcon {
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Column {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 3
                visible: root.sessions.length > 0

                Repeater {
                    model: root.sessions.slice(0, root.maxDots)

                    SessionDot {}
                }
            }
        }
    }

    ClaudePopup {
        id: claudePopout

        sessions: root.sessions
        requests: root.requests
        onShownChanged: root.setPopoutOpen(shown)
        onResponded: (id, action, answers) => root.submit(id, action, answers)
        onSessionActivated: session => root.focusSession(session)
    }
}
