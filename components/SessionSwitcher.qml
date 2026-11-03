import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Common
import qs.Services
import qs.Widgets
import qs.DCommon.Widgets as D
import "../lib/SessionModel.js" as Model
import "../lib/Phase.js" as Phase

// Spotlight-style picker: a search pill centered near the top third of the focused
// screen, with the matching sessions below it. It owns the keyboard while open.
Scope {
    id: root

    property var sessions: []
    property bool shown: false
    property int selectedIndex: 0
    property string query: ""
    property var targetScreen: null
    readonly property var results: Model.filterSessions(sessions, query)

    readonly property real rowHeight: Theme.listItemHeight
    readonly property real rowGap: Theme.groupedListGap
    readonly property real inset: Theme.spacingM
    readonly property color surfaceColor: Theme.floatingWindowSurface
    readonly property bool darken: SettingsData.modalDarkenBackground

    signal activated(var session)

    function tr(text) {
        return I18n.trFor("claudeSessions", text);
    }

    function open() {
        targetScreen = CompositorService.getFocusedScreen() ?? Quickshell.screens[0] ?? null;
        field.text = "";
        query = "";
        selectedIndex = 0;
        shown = true;
        Qt.callLater(() => field.forceActiveFocus());
    }

    function close() {
        shown = false;
    }

    function toggle() {
        if (shown)
            close();
        else
            open();
    }

    function move(delta) {
        const count = results.length;
        if (count > 0)
            selectedIndex = (selectedIndex + delta + count) % count;
    }

    function accept(index) {
        const session = results[index];
        if (!session)
            return;
        close();
        activated(session);
    }

    onResultsChanged: selectedIndex = Math.max(0, Math.min(selectedIndex, results.length - 1))

    PanelWindow {
        id: win

        readonly property real screenWidth: screen ? screen.width : Theme.launcherWidthWide
        readonly property real screenHeight: screen ? screen.height : 0

        screen: root.targetScreen
        visible: root.shown || fade.running
        color: "transparent"

        WlrLayershell.namespace: "dms:plugins:claude-sessions-switcher"
        WlrLayershell.layer: WlrLayershell.Overlay
        WlrLayershell.exclusiveZone: -1
        WlrLayershell.keyboardFocus: root.shown ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

        anchors {
            top: true
            left: true
            right: true
            bottom: true
        }

        WindowBlur {
            targetWindow: win
            surfaceColor: root.surfaceColor
            blurX: card.x
            blurY: card.y
            blurWidth: root.shown ? card.width : 0
            blurHeight: root.shown ? card.height : 0
            blurRadius: Theme.windowRadius
        }

        Rectangle {
            anchors.fill: parent
            visible: root.darken
            color: Theme.scrimColor
            opacity: root.shown ? Theme.scrimAlpha : 0

            Behavior on opacity {
                NumberAnimation {
                    duration: SettingsData.reduceMotion ? 0 : Theme.popoutAnimationDuration
                }
            }
        }

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onClicked: root.close()
        }

        Item {
            id: card

            width: Math.min(Theme.launcherWidthWide, win.screenWidth - Theme.launcherScreenMargin * 2)
            height: column.implicitHeight + root.inset * 2
            x: Math.round((win.screenWidth - width) / 2)
            // Same anchor as Spotlight: the search pill sits on the upper third.
            y: Math.round(Math.max(Theme.launcherScreenMargin, win.screenHeight * 0.33 - root.rowHeight / 2 - root.inset))
            opacity: root.shown ? 1 : 0
            scale: root.shown ? 1 : 0.98

            Behavior on opacity {
                NumberAnimation {
                    id: fade

                    duration: SettingsData.reduceMotion ? 0 : Theme.popoutAnimationDuration
                    easing.type: Easing.OutCubic
                }
            }

            Behavior on scale {
                NumberAnimation {
                    duration: SettingsData.reduceMotion ? 0 : Theme.popoutAnimationDuration
                    easing.type: Easing.OutCubic
                }
            }

            // Clicks on the card must not reach the dismiss area behind it.
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.AllButtons
            }

            ElevationShadow {
                anchors.fill: parent
                level: Theme.elevationLevel3
                fallbackOffset: Theme.spacingXS
                targetColor: root.surfaceColor
                targetRadius: Theme.windowRadius
                borderWidth: 0
                shadowEnabled: Theme.elevationEnabled && SettingsData.popoutElevationEnabled
            }

            Item {
                id: keys

                Keys.onPressed: event => {
                    const ctrl = event.modifiers & Qt.ControlModifier;
                    if (event.key === Qt.Key_Escape) {
                        root.close();
                    } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                        root.accept(root.selectedIndex);
                    } else if (event.key === Qt.Key_Down || event.key === Qt.Key_Tab || (ctrl && (event.key === Qt.Key_N || event.key === Qt.Key_J))) {
                        root.move(1);
                    } else if (event.key === Qt.Key_Up || event.key === Qt.Key_Backtab || (ctrl && (event.key === Qt.Key_P || event.key === Qt.Key_K))) {
                        root.move(-1);
                    } else {
                        return;
                    }
                    event.accepted = true;
                }
            }

            Column {
                id: column

                x: root.inset
                y: root.inset
                width: parent.width - root.inset * 2
                spacing: Theme.spacingS

                D.DSearchField {
                    id: field

                    width: parent.width
                    height: root.rowHeight
                    textColor: Theme.onSurface
                    font.pixelSize: Theme.fontSizeLarge
                    backgroundColor: Theme.chipSurface
                    borderWidth: 0
                    focusedBorderWidth: 0
                    placeholderText: root.tr("Switch Claude session") + "…"
                    keyForwardTargets: [keys]
                    leadingContent: Component {
                        ClaudeLogo {
                            size: field.leftIconSize
                            color: field.activeFocus ? field.leftIconFocusedColor : field.leftIconColor
                        }
                    }
                    onTextChanged: root.query = text
                }

                ListView {
                    id: list

                    width: parent.width
                    height: Math.min(contentHeight, Theme.launcherMaxVisibleRows * (root.rowHeight + root.rowGap))
                    visible: count > 0
                    clip: true
                    spacing: root.rowGap
                    boundsBehavior: Flickable.StopAtBounds
                    model: root.results
                    currentIndex: root.selectedIndex
                    highlightFollowsCurrentItem: false
                    onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)

                    delegate: Rectangle {
                        id: row

                        required property var modelData
                        required property int index
                        readonly property bool selected: index === root.selectedIndex
                        readonly property color statusColor: Phase.color(Theme, modelData.phase)
                        readonly property color contentColor: selected ? Theme.onSelectedContainer : Theme.onSurface
                        readonly property string detail: Phase.detail(modelData)

                        width: list.width
                        height: root.rowHeight
                        radius: Theme.cornerRadius
                        color: selected ? Theme.selectedContainer : rowMouse.containsMouse ? Theme.surfaceHover : "transparent"

                        MouseArea {
                            id: rowMouse

                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onPositionChanged: root.selectedIndex = row.index
                            onClicked: root.accept(row.index)
                        }

                        Rectangle {
                            id: badge

                            x: Theme.spacingM
                            anchors.verticalCenter: parent.verticalCenter
                            width: Theme.avatarSize
                            height: width
                            radius: width / 2
                            color: Theme.withAlpha(row.statusColor, 0.18)

                            D.DIcon {
                                anchors.centerIn: parent
                                name: Phase.icon(row.modelData.phase)
                                size: Theme.iconSizeSmall
                                color: row.statusColor
                            }
                        }

                        Column {
                            anchors.left: badge.right
                            anchors.leftMargin: Theme.spacingM
                            anchors.right: statusLabel.left
                            anchors.rightMargin: Theme.spacingM
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: Theme.spacingXXS

                            StyledText {
                                width: parent.width
                                text: row.modelData.project
                                font.pixelSize: Theme.fontSizeLarge
                                font.weight: Theme.fontWeightMedium
                                color: row.contentColor
                                elide: Text.ElideRight
                            }

                            StyledText {
                                width: parent.width
                                visible: text.length > 0
                                text: row.detail
                                font.pixelSize: Theme.fontSizeSmall
                                color: row.selected ? Theme.withAlpha(Theme.onSelectedContainer, 0.75) : Theme.surfaceVariantText
                                elide: Text.ElideRight
                                maximumLineCount: 1
                            }
                        }

                        StyledText {
                            id: statusLabel

                            anchors.right: parent.right
                            anchors.rightMargin: Theme.spacingM
                            anchors.verticalCenter: parent.verticalCenter
                            text: root.tr(Phase.label(row.modelData.phase))
                            font.pixelSize: Theme.fontSizeSmall
                            color: row.statusColor
                        }
                    }
                }

                StyledText {
                    width: parent.width
                    visible: list.count === 0
                    text: root.sessions.length ? root.tr("No matching sessions") : root.tr("No Claude sessions")
                    color: Theme.surfaceVariantText
                    horizontalAlignment: Text.AlignHCenter
                    topPadding: Theme.spacingS
                    bottomPadding: Theme.spacingS
                }
            }
        }
    }
}
