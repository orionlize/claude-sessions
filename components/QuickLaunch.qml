import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Common
import qs.Services
import qs.Widgets
import qs.DCommon.Widgets as D
import "../lib/Folders.js" as Folders
import "../lib/LaunchOptions.js" as LaunchOptions

// Global quick-entry box, like Claude Desktop's: type a prompt, press Enter, and a new
// Claude Code session starts silently in the claude-quick tmux session. Like Desktop's new-session screen, a
// folder control under the prompt picks where it runs: recent folders, any typed
// path, or a fresh temporary folder. Model and effort chips beside it open a
// dropdown on click (or Ctrl+M / Ctrl+E); the mouse wheel over a chip steps through
// its choices without opening it.
// It owns the keyboard while open.
Scope {
    id: root

    property bool shown: false
    property var targetScreen: null
    property string pluginDir: ""
    // "" starts in a new /tmp/<uuid> folder.
    property string folder: ""
    property var recentFolders: []
    property string model: LaunchOptions.DEFAULT_MODEL
    property string effort: LaunchOptions.DEFAULT_EFFORT
    property var modelOptions: LaunchOptions.MODELS

    property bool picking: false
    property string folderQuery: ""
    property var completions: []
    property int folderIndex: 0
    // "" when closed, else "model" or "effort".
    property string optionMenu: ""
    property int optionIndex: 0
    readonly property var optionItems: optionMenu === "model" ? modelOptions : optionMenu === "effort" ? LaunchOptions.EFFORTS : []
    readonly property string home: Quickshell.env("HOME") || ""
    readonly property var folderItems: Folders.items(recentFolders, completions, folderQuery, home)

    readonly property real inset: Theme.spacingM
    readonly property real pillHeight: Theme.listItemHeight
    readonly property color surfaceColor: Theme.floatingWindowSurface
    readonly property bool darken: SettingsData.modalDarkenBackground

    signal submitted(string prompt, string folder, string model, string effort)

    function tr(text) {
        return I18n.trFor("claudeSessions", text);
    }

    function open() {
        targetScreen = CompositorService.getFocusedScreen() ?? Quickshell.screens[0] ?? null;
        input.text = "";
        picking = false;
        optionMenu = "";
        shown = true;
        Qt.callLater(() => input.forceActiveFocus());
    }

    function close() {
        shown = false;
        picking = false;
        optionMenu = "";
    }

    function folderLabel(path) {
        return path ? Folders.folderName(path) : tr("New temporary folder");
    }

    function openPicker() {
        folderField.text = "";
        folderQuery = "";
        completions = [];
        optionMenu = "";
        folderIndex = Math.max(0, folderItems.findIndex(item => item.path === folder));
        picking = true;
        Qt.callLater(() => folderField.forceActiveFocus());
    }

    function closePicker() {
        picking = false;
        Qt.callLater(() => input.forceActiveFocus());
    }

    function cycleModel(delta) {
        model = LaunchOptions.cycle(modelOptions, model, delta);
    }

    function cycleEffort(delta) {
        effort = LaunchOptions.cycle(LaunchOptions.EFFORTS, effort, delta);
    }

    function openOptions(kind) {
        picking = false;
        optionMenu = kind;
        optionIndex = Math.max(0, optionItems.indexOf(kind === "model" ? model : effort));
        Qt.callLater(() => optionKeys.forceActiveFocus());
    }

    function toggleOptions(kind) {
        if (optionMenu === kind)
            closeOptions();
        else
            openOptions(kind);
    }

    function closeOptions() {
        optionMenu = "";
        Qt.callLater(() => input.forceActiveFocus());
    }

    function moveOption(delta) {
        const count = optionItems.length;
        if (count > 0)
            optionIndex = (optionIndex + delta + count) % count;
    }

    function chooseOption(index) {
        const value = optionItems[index];
        if (value === undefined)
            return;
        if (optionMenu === "model")
            model = value;
        else if (optionMenu === "effort")
            effort = value;
        closeOptions();
    }

    function moveFolder(delta) {
        const count = folderItems.length;
        if (count > 0)
            folderIndex = (folderIndex + delta + count) % count;
    }

    function chooseFolder(index) {
        const item = folderItems[index];
        if (item)
            folder = item.path;
        else if (Folders.looksLikePath(folderQuery))
            folder = Folders.expand(folderQuery, home);
        else
            return;
        closePicker();
    }

    // Tab fills in the selected folder, like shell completion, so you can keep typing below it.
    function completeFolder() {
        const item = folderItems[folderIndex];
        if (!item || !item.path)
            return;
        folderField.text = Folders.shorten(item.path, home) + "/";
        folderField.cursorPosition = folderField.text.length;
    }

    function requestCompletions() {
        if (!Folders.looksLikePath(folderQuery) || !pluginDir) {
            completions = [];
            return;
        }
        completer.running = false;
        completer.command = ["python3", "-S", pluginDir + "/scripts/complete-dir.py", folderQuery];
        completer.running = true;
    }

    onFolderItemsChanged: folderIndex = Math.max(0, Math.min(folderIndex, folderItems.length - 1))
    onFolderQueryChanged: completeTimer.restart()

    Timer {
        id: completeTimer

        interval: 60
        onTriggered: root.requestCompletions()
    }

    Process {
        id: completer

        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    root.completions = JSON.parse(text);
                } catch (e) {
                    root.completions = [];
                }
            }
        }
    }

    function toggle() {
        if (shown)
            close();
        else
            open();
    }

    function submit() {
        const prompt = input.text.trim();
        close();
        submitted(prompt, folder, model, effort);
    }

    PanelWindow {
        id: win

        readonly property real screenWidth: screen ? screen.width : Theme.launcherWidthWide
        readonly property real screenHeight: screen ? screen.height : 0

        screen: root.targetScreen
        visible: root.shown || fade.running
        color: "transparent"

        WlrLayershell.namespace: "dms:plugins:claude-quick-launch"
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
            // Grows downward from a fixed top, so typing more lines never moves the caret.
            y: Math.round(Math.max(Theme.launcherScreenMargin, win.screenHeight * 0.33 - root.pillHeight / 2 - root.inset))
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

            Column {
                id: column

                x: root.inset
                y: root.inset
                width: parent.width - root.inset * 2
                spacing: Theme.spacingS

                Rectangle {
                    id: pill

                    width: parent.width
                    // The first line is centered on the logo; extra lines grow the pill downward.
                    height: Math.max(root.pillHeight, scroller.y * 2 + scroller.height)
                    radius: Theme.cornerRadius
                    color: Theme.chipSurface

                    ClaudeLogo {
                        id: logo

                        x: Theme.spacingM
                        y: Math.round((root.pillHeight - height) / 2)
                        size: Theme.iconSize
                        color: Theme.primary
                    }

                    Flickable {
                        id: scroller

                        anchors.left: logo.right
                        anchors.leftMargin: Theme.spacingM
                        anchors.right: send.left
                        anchors.rightMargin: Theme.spacingS
                        y: Math.round((root.pillHeight - input.lineHeight) / 2)
                        height: Math.min(Math.max(input.contentHeight, input.lineHeight), input.maxHeight)
                        contentWidth: width
                        contentHeight: input.contentHeight
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds

                        TextEdit {
                            id: input

                            width: scroller.width
                            wrapMode: TextEdit.Wrap
                            color: Theme.onSurface
                            selectionColor: Theme.withAlpha(Theme.primary, 0.35)
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeLarge
                            // Up to six lines show before the box scrolls.
                            readonly property real lineHeight: metrics.height
                            readonly property real maxHeight: lineHeight * 6
                            onCursorRectangleChanged: {
                                const r = cursorRectangle;
                                if (r.y < scroller.contentY)
                                    scroller.contentY = r.y;
                                else if (r.y + r.height > scroller.contentY + scroller.height)
                                    scroller.contentY = r.y + r.height - scroller.height;
                            }

                            Keys.onPressed: event => {
                                const shift = event.modifiers & Qt.ShiftModifier;
                                const ctrl = event.modifiers & Qt.ControlModifier;
                                if (event.key === Qt.Key_Escape) {
                                    root.close();
                                } else if (event.key === Qt.Key_Tab) {
                                    root.openPicker();
                                } else if (ctrl && event.key === Qt.Key_M) {
                                    root.openOptions("model");
                                } else if (ctrl && event.key === Qt.Key_E) {
                                    root.openOptions("effort");
                                } else if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && !shift) {
                                    root.submit();
                                } else {
                                    return;
                                }
                                event.accepted = true;
                            }

                            FontMetrics {
                                id: metrics

                                font: input.font
                            }

                            // Same font and origin as the TextEdit, so it lines up with typed text.
                            Text {
                                visible: input.text.length === 0 && !input.preeditText
                                text: root.tr("How can I help you today?")
                                font: input.font
                                color: Theme.withAlpha(Theme.surfaceVariantText, 0.4)
                            }
                        }
                    }

                    Rectangle {
                        id: send

                        readonly property bool ready: input.text.trim().length > 0

                        anchors.right: parent.right
                        anchors.rightMargin: Theme.spacingS
                        y: Math.round((root.pillHeight - height) / 2)
                        width: root.pillHeight - Theme.spacingS * 2
                        height: width
                        radius: Theme.cornerRadius
                        color: ready ? Theme.primary : Theme.withAlpha(Theme.onSurface, 0.08)

                        D.DIcon {
                            anchors.centerIn: parent
                            name: "arrow_upward"
                            size: Theme.iconSizeSmall
                            color: send.ready ? Theme.onPrimary : Theme.surfaceVariantText
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.submit()
                        }
                    }
                }

                // The row under the prompt, as on Desktop's new-session screen.
                Item {
                    id: optionBar

                    width: parent.width
                    height: folderChip.height

                    Rectangle {
                        id: folderChip

                        readonly property bool active: root.picking || chipMouse.containsMouse

                        width: Math.min(chipRow.implicitWidth + Theme.spacingS * 2, parent.width * 0.45)
                        height: Theme.iconSize + Theme.spacingS
                        radius: Theme.cornerRadius
                        color: active ? Theme.surfaceHover : Theme.withAlpha(Theme.onSurface, 0.05)

                        Row {
                            id: chipRow

                            x: Theme.spacingS
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: Theme.spacingXS

                            D.DIcon {
                                anchors.verticalCenter: parent.verticalCenter
                                name: root.folder ? "folder" : "folder_special"
                                size: Theme.iconSizeSmall
                                color: Theme.surfaceVariantText
                            }

                            StyledText {
                                anchors.verticalCenter: parent.verticalCenter
                                width: Math.min(implicitWidth, folderChip.parent.width * 0.45 - Theme.iconSizeSmall * 2 - Theme.spacingS * 3)
                                text: root.folderLabel(root.folder)
                                font.pixelSize: Theme.fontSizeSmall
                                color: Theme.onSurface
                                elide: Text.ElideMiddle
                            }

                            D.DIcon {
                                anchors.verticalCenter: parent.verticalCenter
                                name: root.picking ? "expand_less" : "expand_more"
                                size: Theme.iconSizeSmall
                                color: Theme.surfaceVariantText
                            }
                        }

                        MouseArea {
                            id: chipMouse

                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.picking ? root.closePicker() : root.openPicker()
                        }
                    }

                    Row {
                        id: optionChips

                        anchors.left: folderChip.right
                        anchors.leftMargin: Theme.spacingS
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: Theme.spacingS

                        OptionChip {
                            id: modelChip

                            icon: "neurology"
                            text: root.model
                            open: root.optionMenu === "model"
                            onClicked: root.toggleOptions("model")
                            onStep: delta => root.cycleModel(delta)
                        }

                        OptionChip {
                            id: effortChip

                            icon: "speed"
                            text: root.effort
                            open: root.optionMenu === "effort"
                            onClicked: root.toggleOptions("effort")
                            onStep: delta => root.cycleEffort(delta)
                        }
                    }

                    StyledText {
                        anchors.left: optionChips.right
                        anchors.leftMargin: Theme.spacingM
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        horizontalAlignment: Text.AlignRight
                        text: root.picking ? root.tr("Enter to choose · Tab to complete · Esc to go back") : root.optionMenu ? root.tr("↑↓ to move · Enter to choose · Esc to go back") : root.tr("Enter to start · Tab for folder · Ctrl+M model · Ctrl+E effort")
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.withAlpha(Theme.surfaceVariantText, 0.7)
                        elide: Text.ElideRight
                    }
                }

                Item {
                    id: folderKeys

                    Keys.onPressed: event => {
                        const ctrl = event.modifiers & Qt.ControlModifier;
                        if (event.key === Qt.Key_Escape) {
                            root.closePicker();
                        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                            root.chooseFolder(root.folderIndex);
                        } else if (event.key === Qt.Key_Tab) {
                            root.completeFolder();
                        } else if (event.key === Qt.Key_Down || (ctrl && (event.key === Qt.Key_N || event.key === Qt.Key_J))) {
                            root.moveFolder(1);
                        } else if (event.key === Qt.Key_Up || event.key === Qt.Key_Backtab || (ctrl && (event.key === Qt.Key_P || event.key === Qt.Key_K))) {
                            root.moveFolder(-1);
                        } else {
                            return;
                        }
                        event.accepted = true;
                    }
                }

                Column {
                    width: parent.width
                    visible: root.picking
                    spacing: Theme.spacingS

                    D.DSearchField {
                        id: folderField

                        width: parent.width
                        height: root.pillHeight
                        textColor: Theme.onSurface
                        backgroundColor: Theme.chipSurface
                        borderWidth: 0
                        focusedBorderWidth: 0
                        placeholderText: root.tr("Search recent folders, or type a path like ~/projects")
                        keyForwardTargets: [folderKeys]
                        leadingContent: Component {
                            D.DIcon {
                                name: "folder_open"
                                size: folderField.leftIconSize
                                color: folderField.activeFocus ? folderField.leftIconFocusedColor : folderField.leftIconColor
                            }
                        }
                        onTextChanged: root.folderQuery = text
                    }

                    ListView {
                        id: folderList

                        width: parent.width
                        height: Math.min(contentHeight, Theme.launcherMaxVisibleRows * (root.pillHeight + Theme.groupedListGap))
                        visible: count > 0
                        clip: true
                        spacing: Theme.groupedListGap
                        boundsBehavior: Flickable.StopAtBounds
                        model: root.folderItems
                        currentIndex: root.folderIndex
                        highlightFollowsCurrentItem: false
                        onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)

                        delegate: Rectangle {
                            id: folderRow

                            required property var modelData
                            required property int index
                            readonly property bool selected: index === root.folderIndex
                            readonly property bool current: modelData.path === root.folder
                            readonly property color contentColor: selected ? Theme.onSelectedContainer : Theme.onSurface

                            width: folderList.width
                            height: root.pillHeight
                            radius: Theme.cornerRadius
                            color: selected ? Theme.selectedContainer : rowMouse.containsMouse ? Theme.surfaceHover : "transparent"

                            MouseArea {
                                id: rowMouse

                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onPositionChanged: root.folderIndex = folderRow.index
                                onClicked: root.chooseFolder(folderRow.index)
                            }

                            D.DIcon {
                                id: rowIcon

                                x: Theme.spacingM
                                anchors.verticalCenter: parent.verticalCenter
                                name: folderRow.modelData.path ? "folder" : "folder_special"
                                size: Theme.iconSize
                                color: folderRow.selected ? Theme.onSelectedContainer : Theme.surfaceVariantText
                            }

                            Column {
                                anchors.left: rowIcon.right
                                anchors.leftMargin: Theme.spacingM
                                anchors.right: check.left
                                anchors.rightMargin: Theme.spacingM
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: Theme.spacingXXS

                                StyledText {
                                    width: parent.width
                                    text: root.folderLabel(folderRow.modelData.path)
                                    font.weight: Theme.fontWeightMedium
                                    color: folderRow.contentColor
                                    elide: Text.ElideRight
                                }

                                StyledText {
                                    width: parent.width
                                    text: folderRow.modelData.path ? Folders.shorten(folderRow.modelData.path, root.home) : "/tmp/<uuid>"
                                    font.pixelSize: Theme.fontSizeSmall
                                    color: folderRow.selected ? Theme.withAlpha(Theme.onSelectedContainer, 0.75) : Theme.surfaceVariantText
                                    elide: Text.ElideMiddle
                                }
                            }

                            D.DIcon {
                                id: check

                                anchors.right: parent.right
                                anchors.rightMargin: Theme.spacingM
                                anchors.verticalCenter: parent.verticalCenter
                                visible: folderRow.current
                                name: "check"
                                size: Theme.iconSizeSmall
                                color: folderRow.contentColor
                            }
                        }
                    }

                    StyledText {
                        width: parent.width
                        visible: folderList.count === 0
                        text: Folders.looksLikePath(root.folderQuery) ? root.tr("No such folder") : root.tr("No matching folders · type a path starting with / or ~")
                        color: Theme.surfaceVariantText
                        horizontalAlignment: Text.AlignHCenter
                        topPadding: Theme.spacingS
                        bottomPadding: Theme.spacingS
                    }
                }
            }

            // Dropdown for the model / effort chip, opened right under it. It floats over the
            // card (and past its bottom edge) instead of taking space in the column, so
            // opening it never resizes the card.
            Item {
                id: optionKeys

                readonly property var anchorChip: root.optionMenu === "effort" ? effortChip : modelChip

                x: column.x
                y: column.y + optionBar.y + optionBar.height + Theme.spacingXS
                z: 1
                width: column.width
                height: optionPanel.height
                visible: root.optionMenu !== ""

                Keys.onPressed: event => {
                    const ctrl = event.modifiers & Qt.ControlModifier;
                    const shift = event.modifiers & Qt.ShiftModifier;
                    const digit = event.key - Qt.Key_1;
                    if (event.key === Qt.Key_Escape) {
                        root.closeOptions();
                    } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
                        root.chooseOption(root.optionIndex);
                    } else if (event.key === Qt.Key_Down || event.key === Qt.Key_Tab || (ctrl && (event.key === Qt.Key_N || event.key === Qt.Key_J))) {
                        root.moveOption(1);
                    } else if (event.key === Qt.Key_Up || event.key === Qt.Key_Backtab || (ctrl && (event.key === Qt.Key_P || event.key === Qt.Key_K))) {
                        root.moveOption(-1);
                    } else if (ctrl && event.key === Qt.Key_M) {
                        if (root.optionMenu === "model")
                            root.moveOption(shift ? -1 : 1);
                        else
                            root.openOptions("model");
                    } else if (ctrl && event.key === Qt.Key_E) {
                        if (root.optionMenu === "effort")
                            root.moveOption(shift ? -1 : 1);
                        else
                            root.openOptions("effort");
                    } else if (!event.modifiers && digit >= 0 && digit < Math.min(9, root.optionItems.length)) {
                        root.chooseOption(digit);
                    } else {
                        return;
                    }
                    event.accepted = true;
                }

                Rectangle {
                    id: optionPanel

                    width: Math.min(parent.width, Math.max(optionKeys.anchorChip.width, Theme.launcherWidthWide * 0.25))
                    height: optionList.height + Theme.spacingXS * 2
                    // Lines up with the chip that opened it, kept inside the card.
                    x: Math.min(parent.width - width, optionChips.x + optionKeys.anchorChip.x)
                    radius: Theme.cornerRadius
                    color: Theme.chipSurface

                    ElevationShadow {
                        anchors.fill: parent
                        z: -1
                        level: Theme.elevationLevel2
                        fallbackOffset: Theme.spacingXXS
                        targetColor: Theme.chipSurface
                        targetRadius: Theme.cornerRadius
                        borderWidth: 0
                        shadowEnabled: Theme.elevationEnabled && SettingsData.popoutElevationEnabled
                    }

                    // Past the card's edge, clicks would otherwise reach the backdrop and close.
                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.AllButtons
                    }

                    ListView {
                        id: optionList

                        x: Theme.spacingXS
                        y: Theme.spacingXS
                        width: parent.width - Theme.spacingXS * 2
                        height: Math.min(contentHeight, Theme.launcherMaxVisibleRows * (root.pillHeight * 0.8 + Theme.groupedListGap))
                        clip: true
                        spacing: Theme.groupedListGap
                        boundsBehavior: Flickable.StopAtBounds
                        model: root.optionItems
                        currentIndex: root.optionIndex
                        highlightFollowsCurrentItem: false
                        onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)

                        delegate: Rectangle {
                            id: optionRow

                            required property var modelData
                            required property int index
                            readonly property bool selected: index === root.optionIndex
                            readonly property bool current: modelData === (root.optionMenu === "model" ? root.model : root.effort)
                            readonly property color contentColor: selected ? Theme.onSelectedContainer : Theme.onSurface

                            width: optionList.width
                            height: Math.round(root.pillHeight * 0.8)
                            radius: Theme.cornerRadius
                            color: selected ? Theme.selectedContainer : optionRowMouse.containsMouse ? Theme.surfaceHover : "transparent"

                            MouseArea {
                                id: optionRowMouse

                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onPositionChanged: root.optionIndex = optionRow.index
                                onClicked: root.chooseOption(optionRow.index)
                            }

                            StyledText {
                                x: Theme.spacingM
                                anchors.right: optionCheck.left
                                anchors.rightMargin: Theme.spacingS
                                anchors.verticalCenter: parent.verticalCenter
                                text: optionRow.modelData
                                color: optionRow.contentColor
                                font.weight: optionRow.current ? Theme.fontWeightMedium : Font.Normal
                                elide: Text.ElideRight
                            }

                            D.DIcon {
                                id: optionCheck

                                anchors.right: parent.right
                                anchors.rightMargin: Theme.spacingM
                                anchors.verticalCenter: parent.verticalCenter
                                visible: optionRow.current
                                name: "check"
                                size: Theme.iconSizeSmall
                                color: optionRow.contentColor
                            }
                        }
                    }
                }
            }
        }
    }

    // Click opens the dropdown; the wheel steps through the choices in place.
    component OptionChip: Rectangle {
        id: chip

        property string icon: ""
        property string text: ""
        property bool open: false
        signal clicked
        signal step(int delta)

        width: optionRow.implicitWidth + Theme.spacingS * 2
        height: Theme.iconSize + Theme.spacingS
        radius: Theme.cornerRadius
        color: open || optionMouse.containsMouse ? Theme.surfaceHover : Theme.withAlpha(Theme.onSurface, 0.05)

        Row {
            id: optionRow

            x: Theme.spacingS
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.spacingXS

            D.DIcon {
                anchors.verticalCenter: parent.verticalCenter
                name: chip.icon
                size: Theme.iconSizeSmall
                color: Theme.surfaceVariantText
            }

            StyledText {
                anchors.verticalCenter: parent.verticalCenter
                text: chip.text
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.onSurface
            }

            D.DIcon {
                anchors.verticalCenter: parent.verticalCenter
                name: chip.open ? "expand_less" : "expand_more"
                size: Theme.iconSizeSmall
                color: Theme.surfaceVariantText
            }
        }

        MouseArea {
            id: optionMouse

            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: chip.clicked()
            onWheel: wheel => chip.step(wheel.angleDelta.y > 0 ? -1 : 1)
        }
    }
}
