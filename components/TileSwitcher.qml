import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Common
import qs.Services
import qs.Widgets
import "../lib/Phase.js" as Phase

// Alt-Tab style picker: every session is a tile laid out in a grid centered on the
// focused screen. A tile shows a snapshot of the session's tmux pane, or its latest
// turns when it does not run in tmux.
Scope {
    id: root

    property var sessions: []
    property string pluginDir: ""
    property bool shown: false
    property int selectedIndex: 0
    property var targetScreen: null
    property var previews: ({})

    // Tiles have one fixed size, whatever the number of sessions: it is the size
    // that fits a reference grid of refColumns x refRows on screen. Sessions fill
    // as many columns as fit; extra rows scroll.
    readonly property int count: Math.max(1, sessions.length)
    readonly property int refColumns: 2
    readonly property int refRows: 2
    readonly property int maxColumns: Math.max(1, Math.floor((availableWidth + gap) / (tileWidth + gap)))
    readonly property int columns: Math.min(count, maxColumns)
    readonly property real headerHeight: Theme.avatarSize + Theme.spacingM + Theme.spacingS * 2
    // Width : height of the preview area, close to a typical terminal pane.
    readonly property real previewAspect: 0.55
    readonly property real availableWidth: win.screenWidth * 0.9 - inset * 2
    readonly property real availableHeight: win.screenHeight * 0.88 - inset * 2
    readonly property real tileWidth: Math.floor(Math.min(1500,
        (availableWidth - gap * (refColumns - 1)) / refColumns,
        ((availableHeight - gap * (refRows - 1)) / refRows - headerHeight) / previewAspect))
    readonly property real tileHeight: Math.floor(headerHeight + tileWidth * previewAspect)
    readonly property real gap: Theme.spacingL
    readonly property real inset: 0
    readonly property color surfaceColor: Theme.floatingWindowSurface
    // Tiles follow the floating-window transparency setting; the window blurs behind them.
    readonly property real tileColorAlpha: Theme.floatingWindowTransparency

    signal activated(var session)

    function tr(text) {
        return I18n.trFor("claudeSessions", text);
    }

    function open() {
        targetScreen = CompositorService.getFocusedScreen() ?? Quickshell.screens[0] ?? null;
        selectedIndex = 0;
        previews = {};
        shown = true;
        refresh();
        Qt.callLater(() => keys.forceActiveFocus());
    }

    function escapeHtml(text) {
        return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
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
        const count = sessions.length;
        if (count > 0)
            selectedIndex = (selectedIndex + delta + count) % count;
    }

    // Up and down keep the column; past the last row they stop instead of wrapping.
    function moveRow(delta) {
        const next = selectedIndex + delta * grid.columns;
        if (next >= 0 && next < sessions.length)
            selectedIndex = next;
    }

    function accept(index) {
        const session = sessions[index];
        if (!session)
            return;
        close();
        activated(session);
    }

    function refresh() {
        if (!pluginDir || reader.running || !sessions.length)
            return;
        reader.command = ["python3", "-S", pluginDir + "/scripts/preview.py", JSON.stringify(sessions.map(s => ({
                    id: s.id,
                    pid: s.pid || 0,
                    tmux: s.tmux || "",
                    pane: s.tmuxPane || "",
                    transcript: s.transcript || ""
                })))];
        reader.running = true;
    }

    onSessionsChanged: selectedIndex = Math.max(0, Math.min(selectedIndex, sessions.length - 1))

    Process {
        id: reader

        stdout: StdioCollector {
            id: readerOutput
        }
        onExited: exitCode => {
            if (exitCode !== 0)
                return;
            try {
                root.previews = JSON.parse(readerOutput.text);
            } catch (e) {
                console.warn("claudeSessions: bad preview output:", e);
            }
        }
    }

    Timer {
        interval: 1500
        repeat: true
        running: root.shown
        onTriggered: root.refresh()
    }

    PanelWindow {
        id: win

        readonly property real screenWidth: screen ? screen.width : 1280
        readonly property real screenHeight: screen ? screen.height : 800

        screen: root.targetScreen
        visible: root.shown || fade.running
        color: "transparent"

        WlrLayershell.namespace: "dms:plugins:claude-sessions-tiles"
        WlrLayershell.layer: WlrLayershell.Overlay
        WlrLayershell.exclusiveZone: -1
        WlrLayershell.keyboardFocus: root.shown ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

        anchors {
            top: true
            left: true
            right: true
            bottom: true
        }

        // Each tile is translucent, so the window blurs behind every tile: one sub-region
        // per tile, cut to the scroll viewport. Tiles register themselves as they come
        // and go; the region is rebuilt from the current set.
        property var blurRegion: null
        property var blurTiles: []

        BackgroundEffect.blurRegion: root.shown && BlurService.enabled && root.tileColorAlpha < 1 ? blurRegion : null

        function registerBlurTile(item) {
            if (blurTiles.indexOf(item) < 0) {
                blurTiles = blurTiles.concat([item]);
                blurRebuild.restart();
            }
        }

        function unregisterBlurTile(item) {
            const i = blurTiles.indexOf(item);
            if (i < 0)
                return;
            const next = blurTiles.slice();
            next.splice(i, 1);
            blurTiles = next;
            blurRebuild.restart();
        }

        // A Region tracks its item's own geometry only; scrolling or scaling an
        // ancestor needs an explicit nudge.
        function refreshBlur() {
            if (blurRegion)
                blurRegion.changed();
        }

        function rebuildBlur() {
            const old = blurRegion;
            blurRegion = null;
            if (old)
                old.destroy();
            if (!blurTiles.length)
                return;
            const region = blurRegionComp.createObject(win);
            const subs = blurTiles.map(t => blurTileComp.createObject(region, {
                    tile: t
                }));
            subs.push(blurClipComp.createObject(region));
            region.regions = subs;
            blurRegion = region;
        }

        Timer {
            id: blurRebuild

            interval: 1
            onTriggered: win.rebuildBlur()
        }

        Component {
            id: blurRegionComp

            Region {}
        }

        Component {
            id: blurTileComp

            Region {
                property Item tile

                item: tile
                radius: Theme.cornerRadiusL
            }
        }

        Component {
            id: blurClipComp

            Region {
                intersection: Intersection.Intersect
                item: flick
            }
        }

        Connections {
            target: flick
            function onContentYChanged() {
                win.refreshBlur();
            }
        }

        Connections {
            target: card
            function onScaleChanged() {
                win.refreshBlur();
            }
            function onXChanged() {
                win.refreshBlur();
            }
            function onYChanged() {
                win.refreshBlur();
            }
        }

        Rectangle {
            anchors.fill: parent
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
            id: keys

            focus: true
            // Alt-Tab: letting go of the modifier that opened the tiles picks the selection.
            Keys.onReleased: event => {
                if (event.isAutoRepeat)
                    return;
                if (event.key === Qt.Key_Meta || event.key === Qt.Key_Super_L || event.key === Qt.Key_Super_R || event.key === Qt.Key_Alt) {
                    event.accepted = true;
                    root.accept(root.selectedIndex);
                }
            }

            Keys.onPressed: event => {
                const ctrl = event.modifiers & Qt.ControlModifier;
                const digit = event.key - Qt.Key_1;
                if (event.key === Qt.Key_Escape) {
                    root.close();
                } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
                    root.accept(root.selectedIndex);
                } else if (event.key === Qt.Key_Right || event.key === Qt.Key_Tab || event.key === Qt.Key_L || (ctrl && event.key === Qt.Key_N)) {
                    root.move(1);
                } else if (event.key === Qt.Key_Left || event.key === Qt.Key_Backtab || event.key === Qt.Key_H || (ctrl && event.key === Qt.Key_P)) {
                    root.move(-1);
                } else if (event.key === Qt.Key_Down || event.key === Qt.Key_J) {
                    root.moveRow(1);
                } else if (event.key === Qt.Key_Up || event.key === Qt.Key_K) {
                    root.moveRow(-1);
                } else if (digit >= 0 && digit < 9) {
                    root.accept(digit);
                } else {
                    return;
                }
                event.accepted = true;
            }
        }

        Item {
            id: card

            readonly property real maxWidth: win.screenWidth - Theme.launcherScreenMargin * 2
            readonly property real maxHeight: win.screenHeight - Theme.launcherScreenMargin * 2

            width: Math.max(grid.width, empty.implicitWidth) + root.inset * 2
            height: Math.min(maxHeight, grid.height + root.inset * 2)
            x: Math.round((win.screenWidth - width) / 2)
            y: Math.round((win.screenHeight - height) / 2)
            opacity: root.shown ? 1 : 0
            scale: root.shown ? 1 : 0.97

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

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.AllButtons
            }

            // No panel behind the tiles: they sit straight on the scrim. Only the
            // empty message gets a backing so it stays legible.
            Rectangle {
                anchors.fill: empty
                visible: empty.visible
                radius: Theme.cornerRadiusL
                color: root.surfaceColor
            }

            StyledText {
                id: empty

                anchors.centerIn: parent
                visible: root.sessions.length === 0
                text: root.tr("No Claude sessions")
                color: Theme.surfaceVariantText
                padding: Theme.spacingL
            }

            Flickable {
                id: flick

                x: root.inset
                y: root.inset
                width: grid.width
                height: card.height - root.inset * 2
                contentHeight: grid.height
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                Grid {
                    id: grid

                    columns: root.columns
                    spacing: root.gap

                    Repeater {
                        model: root.sessions

                        Tile {}
                    }
                }
            }
        }
    }

    component Tile: Rectangle {
        id: tile

        required property var modelData
        required property int index
        readonly property bool selected: index === root.selectedIndex
        readonly property color statusColor: Phase.color(Theme, modelData.phase)
        readonly property var preview: root.previews[modelData.id] || ({})
        readonly property var screen: preview.screen || null
        readonly property var items: preview.items || []

        width: root.tileWidth
        height: root.tileHeight
        radius: Theme.cornerRadiusL
        color: Theme.withAlpha(selected ? Theme.selectedContainer : mouse.containsMouse ? Theme.surfaceContainerHigh : Theme.surfaceContainer, root.tileColorAlpha)
        border.width: selected ? 2 : 0
        border.color: Theme.primary
        scale: selected ? 1 : 0.98

        Component.onCompleted: win.registerBlurTile(tile)
        Component.onDestruction: win.unregisterBlurTile(tile)
        onScaleChanged: win.refreshBlur()

        onSelectedChanged: {
            if (!selected)
                return;
            const top = y, bottom = y + height;
            if (top < flick.contentY)
                flick.contentY = top;
            else if (bottom > flick.contentY + flick.height)
                flick.contentY = bottom - flick.height;
        }

        Behavior on scale {
            NumberAnimation {
                duration: SettingsData.reduceMotion ? 0 : Theme.shortDuration
                easing.type: Easing.OutCubic
            }
        }

        MouseArea {
            id: mouse

            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onPositionChanged: root.selectedIndex = tile.index
            onClicked: root.accept(tile.index)
        }

        Item {
            id: header

            x: Theme.spacingM
            y: Theme.spacingM
            width: parent.width - Theme.spacingM * 2
            height: Theme.avatarSize

            Rectangle {
                id: badge

                width: Theme.avatarSize
                height: width
                radius: width / 2
                color: Theme.withAlpha(tile.statusColor, 0.18)

                ClaudeLogo {
                    anchors.centerIn: parent
                    size: Theme.iconSizeSmall
                    color: tile.statusColor
                }
            }

            Column {
                anchors.left: badge.right
                anchors.leftMargin: Theme.spacingS
                anchors.right: shortcut.left
                anchors.rightMargin: Theme.spacingS
                anchors.verticalCenter: parent.verticalCenter

                StyledText {
                    width: parent.width
                    text: Phase.name(tile.modelData)
                    font.pixelSize: Theme.fontSizeLarge
                    font.weight: Theme.fontWeightMedium
                    color: tile.selected ? Theme.onSelectedContainer : Theme.onSurface
                    elide: Text.ElideRight
                    wrapMode: Text.NoWrap
                }

                StyledText {
                    width: parent.width
                    text: root.tr(Phase.label(tile.modelData.phase))
                    font.pixelSize: Theme.fontSizeSmall
                    color: tile.statusColor
                    elide: Text.ElideRight
                    wrapMode: Text.NoWrap
                }
            }

            StyledText {
                id: shortcut

                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                visible: tile.index < 9
                text: String(tile.index + 1)
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.surfaceVariantText
            }
        }

        // The preview: newest turn at the bottom, older ones cut off at the top.
        Rectangle {
            id: previewBox

            x: Theme.spacingS
            y: header.y + header.height + Theme.spacingS
            width: parent.width - Theme.spacingS * 2
            height: parent.height - y - Theme.spacingS
            radius: Theme.cornerRadius
            color: Theme.withAlpha(Theme.surface, tile.selected ? 0.55 : 0.4)
            clip: true

            Column {
                id: lines

                visible: tile.screen === null
                x: Theme.spacingS
                width: parent.width - Theme.spacingS * 2
                y: Math.min(Theme.spacingS, parent.height - height - Theme.spacingS)
                spacing: Theme.spacingXS

                Repeater {
                    model: tile.items

                    // One transcript item laid out like Claude Code prints it: a bullet in
                    // the gutter, then the text; prompts sit on a tinted band.
                    Item {
                        id: entry

                        required property var modelData
                        readonly property string kind: modelData.kind
                        readonly property bool user: kind === "user"
                        readonly property real pad: user ? Theme.spacingXS : 0
                        readonly property real gutter: Math.round(Theme.fontSizeSmall * 1.5)

                        width: lines.width
                        height: body.height + pad * 2

                        Rectangle {
                            anchors.fill: parent
                            visible: entry.user
                            radius: Theme.cornerRadiusS
                            color: Theme.withAlpha(Theme.surfaceVariantText, 0.14)
                        }

                        StyledText {
                            id: bullet

                            x: entry.pad + (entry.kind === "result" ? entry.gutter * 0.6 : 0)
                            y: entry.pad
                            text: entry.user ? ">" : entry.kind === "result" ? "⎿" : "⏺"
                            font.pixelSize: Theme.fontSizeSmall
                            font.family: terminal.family
                            color: entry.kind === "tool"
                                ? (entry.modelData.state === "ok" ? Theme.success : entry.modelData.state === "error" ? Theme.error : Theme.surfaceVariantText)
                                : entry.kind === "assistant" ? Theme.onSurface : Theme.surfaceVariantText
                        }

                        StyledText {
                            id: body

                            x: bullet.x + entry.gutter
                            y: entry.pad
                            width: entry.width - x - entry.pad
                            textFormat: entry.kind === "assistant" ? Text.MarkdownText : entry.kind === "tool" ? Text.StyledText : Text.PlainText
                            text: entry.kind === "tool"
                                ? "<b>" + root.escapeHtml(entry.modelData.text) + "</b>" + (entry.modelData.arg ? "(" + root.escapeHtml(entry.modelData.arg) + ")" : "")
                                : entry.modelData.text
                            font.pixelSize: Theme.fontSizeSmall
                            font.family: entry.kind === "tool" || entry.kind === "result" ? terminal.family : resolvedFontFamily
                            color: entry.kind === "result"
                                ? (entry.modelData.error ? Theme.error : Theme.surfaceVariantText)
                                : entry.user ? Theme.surfaceText : Theme.onSurface
                            wrapMode: Text.Wrap
                            // Markdown is already cut to length by preview.py; elide only applies to plain text.
                            maximumLineCount: entry.kind === "assistant" ? 1000 : entry.user ? 4 : 1
                            elide: entry.kind === "assistant" ? Text.ElideNone : Text.ElideRight
                            onLinkActivated: link => Qt.openUrlExternally(link)
                        }
                    }
                }
            }

            // The pane as it looks right now, shrunk to fit like a screenshot.
            Item {
                id: terminal

                readonly property color background: Qt.tint(tile.color, previewBox.color)
                // DMS defaults to Fira Code; a missing font would fall back to a proportional one.
                readonly property string family: Qt.fontFamilies().indexOf(SettingsData.monoFontFamily) >= 0 ? SettingsData.monoFontFamily : "monospace"
                readonly property real naturalWidth: tile.screen ? tile.screen.cols * cell.advanceWidth("M") : 1
                // Rich text lines can come out taller than the font metrics say, so trust the layout.
                readonly property real naturalHeight: tile.screen ? Math.max(tile.screen.rows * cell.lineSpacing, screenText.contentHeight) : 1

                anchors.fill: parent
                anchors.margins: Theme.spacingXS
                visible: tile.screen !== null

                FontMetrics {
                    id: cell

                    font: screenText.font
                }

                Text {
                    id: screenText

                    width: terminal.naturalWidth
                    scale: Math.min(terminal.width / terminal.naturalWidth, terminal.height / terminal.naturalHeight)
                    transformOrigin: Item.TopLeft
                    textFormat: Text.RichText
                    wrapMode: Text.NoWrap
                    font.family: terminal.family
                    font.pixelSize: 14
                    color: Theme.onSurface
                    text: tile.screen ? "<pre style=\"margin:0;font-family:'" + terminal.family + "'\">" + tile.screen.html.replace(/@FG@/g, Theme.onSurface.toString()).replace(/@BG@/g, terminal.background.toString()) + "</pre>" : ""
                }
            }

            // Older turns fade out instead of ending on a half-cut line.
            Rectangle {
                width: parent.width
                height: Theme.spacingXL
                visible: lines.visible && lines.y < 0
                gradient: Gradient {
                    GradientStop {
                        position: 0
                        color: Qt.tint(tile.color, previewBox.color)
                    }
                    GradientStop {
                        position: 1
                        color: Theme.withAlpha(Qt.tint(tile.color, previewBox.color), 0)
                    }
                }
            }

            StyledText {
                anchors.centerIn: parent
                visible: tile.screen === null && tile.items.length === 0
                text: tile.modelData.title || tile.modelData.prompt || tile.modelData.cwd || ""
                width: parent.width - Theme.spacingL * 2
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                maximumLineCount: 4
                elide: Text.ElideRight
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.surfaceVariantText
            }
        }
    }
}
