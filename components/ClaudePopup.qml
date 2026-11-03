import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Common
import qs.Services
import qs.Widgets

// DMS popouts paint Theme.readableSurface, which blurs only below full opacity. This popup owns
// its window and uses the floating-window surface, so it is translucent without changing popouts.
Scope {
    id: root

    property var sessions: []
    property var requests: []
    property real cardWidth: 440
    property bool shown: false
    property bool automatic: false

    // A near-black surface over a dark desktop reads as opaque even though it blends and blurs,
    // so the floating-window surface is tinted with the primary color and thinned further.
    readonly property color surfaceColor: Theme.withAlpha(Theme.blend(Theme.hostSurface, Theme.primary, 0.15), Theme.floatingWindowTransparency * 0.5)
    readonly property real screenGap: Theme.spacingS
    readonly property var shadowLevel: Theme.elevationLevel2
    readonly property real shadowFallback: Theme.spacingXS
    readonly property bool shadowEnabled: Theme.elevationEnabled && SettingsData.popoutElevationEnabled
    readonly property real shadowPad: shadowEnabled ? Theme.elevationRenderPadding(shadowLevel, Theme.elevationLightDirection, shadowFallback, 8, 16) : 0

    property var targetScreen: null
    property var trigger: ({
            x: 0,
            y: 0,
            width: 0
        })
    property int barPosition: 0

    signal responded(string id, string action, var answers)
    signal sessionActivated(var session)

    // An automatic popup leaves the keyboard and outside clicks alone: the user may be
    // typing in a terminal. It takes the keyboard only while the pointer is on it.
    function open(anchor, isAutomatic) {
        if (!isAutomatic)
            PopoutManager.closeAllPopouts();
        targetScreen = anchor.screen;
        trigger = anchor.trigger;
        barPosition = anchor.position;
        automatic = isAutomatic;
        dismiss.visible = !isAutomatic;
        shown = true;
        Qt.callLater(() => card.forceActiveFocus());
    }

    function close() {
        shown = false;
        dismiss.visible = false;
    }

    Connections {
        target: PopoutManager

        function onPopoutOpening() {
            root.close();
        }
    }

    PanelWindow {
        id: dismiss

        screen: root.targetScreen
        visible: false
        color: "transparent"
        WlrLayershell.namespace: "dms:plugins:claude-sessions-dismiss"
        WlrLayershell.layer: WlrLayershell.Overlay
        WlrLayershell.exclusiveZone: -1
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

        anchors {
            top: true
            left: true
            right: true
            bottom: true
        }

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onClicked: root.close()
        }
    }

    PanelWindow {
        id: popup

        readonly property real screenWidth: screen ? screen.width : root.cardWidth
        readonly property real screenHeight: screen ? screen.height : 0
        readonly property bool verticalBar: root.barPosition >= 2
        readonly property real availableHeight: {
            if (verticalBar)
                return screenHeight - root.screenGap * 2;
            return root.barPosition === 1 ? root.trigger.y - root.screenGap : screenHeight - root.trigger.y - root.screenGap;
        }
        readonly property real cardHeight: Math.min(body.implicitHeight + PopoutMetrics.contentPadding * 2, availableHeight)
        readonly property real cardX: {
            const raw = root.barPosition === 2 ? root.trigger.x : root.barPosition === 3 ? root.trigger.x - root.cardWidth : root.trigger.x + root.trigger.width / 2 - root.cardWidth / 2;
            return Math.max(root.screenGap, Math.min(screenWidth - root.cardWidth - root.screenGap, raw));
        }
        readonly property real cardY: {
            const raw = verticalBar ? root.trigger.y - cardHeight / 2 : root.barPosition === 1 ? root.trigger.y - cardHeight : root.trigger.y;
            return Math.max(root.screenGap, Math.min(screenHeight - cardHeight - root.screenGap, raw));
        }
        readonly property real windowX: Math.max(0, cardX - root.shadowPad)
        readonly property real windowY: Math.max(0, cardY - root.shadowPad)

        screen: root.targetScreen
        visible: root.shown || fade.running
        color: "transparent"
        implicitWidth: card.x + root.cardWidth + Math.min(root.shadowPad, screenWidth - cardX - root.cardWidth)
        implicitHeight: card.y + cardHeight + Math.min(root.shadowPad, screenHeight - cardY - cardHeight)
        margins.left: windowX
        margins.top: windowY

        WlrLayershell.namespace: "dms:plugins:claude-sessions"
        WlrLayershell.layer: WlrLayershell.Overlay
        WlrLayershell.exclusiveZone: -1
        WlrLayershell.keyboardFocus: KeyboardFocus.keyboardFocus(root.shown, root.automatic && !body.engaged ? WlrKeyboardFocus.None : null)

        anchors {
            top: true
            left: true
        }

        mask: Region {
            item: card
        }

        WindowBlur {
            targetWindow: popup
            surfaceColor: root.surfaceColor
            blurX: card.x
            blurY: card.y
            blurWidth: card.width
            blurHeight: card.height
            blurRadius: Theme.windowRadius
        }

        Item {
            id: card

            x: popup.cardX - popup.windowX
            y: popup.cardY - popup.windowY
            width: root.cardWidth
            height: popup.cardHeight
            focus: true
            opacity: root.shown ? 1 : 0

            Keys.onEscapePressed: root.close()

            Behavior on opacity {
                NumberAnimation {
                    id: fade

                    duration: SettingsData.reduceMotion ? 0 : Theme.popoutAnimationDuration
                    easing.type: Easing.OutCubic
                }
            }

            ElevationShadow {
                anchors.fill: parent
                level: root.shadowLevel
                fallbackOffset: root.shadowFallback
                targetColor: root.surfaceColor
                targetRadius: Theme.windowRadius
                borderColor: BlurService.borderColor
                borderWidth: BlurService.borderWidth
                shadowEnabled: root.shadowEnabled
            }

            Flickable {
                anchors.fill: parent
                anchors.margins: PopoutMetrics.contentPadding
                contentHeight: body.implicitHeight
                interactive: contentHeight > height
                boundsBehavior: Flickable.StopAtBounds
                clip: true

                PopoutBody {
                    id: body

                    width: parent.width
                    sessions: root.sessions
                    requests: root.requests
                    onResponded: (id, action, answers) => root.responded(id, action, answers)
                    onSessionActivated: session => root.sessionActivated(session)
                }
            }
        }
    }
}
