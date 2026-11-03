import QtQuick
import Quickshell.Io
import qs.Common
import qs.DCommon.Widgets
import qs.Modules.Plugins

PluginSettings {
    id: root

    pluginId: "claudeSessions"

    property string hookStatus: "unknown"

    function tr(text) {
        return I18n.trFor("claudeSessions", text);
    }

    function pluginDir() {
        const plugin = pluginService?.availablePlugins?.[pluginId];
        return plugin?.pluginDirectory ?? "";
    }

    function runInstaller(action) {
        if (!pluginDir() || installer.running)
            return;
        installer.command = ["python3", pluginDir() + "/scripts/install-hooks.py", action];
        installer.running = true;
    }

    onPluginServiceChanged: Qt.callLater(() => runInstaller("status"))
    Component.onCompleted: Qt.callLater(() => runInstaller("status"))

    Process {
        id: installer

        stdout: StdioCollector {
            onStreamFinished: root.hookStatus = text.trim() || "error"
        }
    }

    StyledText {
        width: parent.width
        text: root.tr("Add the widget under Settings → Bar Widgets. Enabling this plugin does not add it to a bar.")
        wrapMode: Text.WordWrap
        color: Theme.surfaceVariantText
    }

    StyledText {
        width: parent.width
        text: root.hookStatus === "installed" ? root.tr("Claude Code hooks are installed. Sessions started before installing need a restart.") : root.tr("Claude Code hooks are not installed. Without them the widget receives nothing.")
        wrapMode: Text.WordWrap
        color: root.hookStatus === "installed" ? Theme.success : Theme.warning
    }

    DButton {
        text: root.hookStatus === "installed" ? root.tr("Remove hooks") : root.tr("Install hooks")
        onClicked: root.runInstaller(root.hookStatus === "installed" ? "uninstall" : "install")
    }

    SelectionSetting {
        settingKey: "switcherMode"
        label: root.tr("Session switcher")
        description: root.tr("Mod+Tab opens this one. Tiles show each session's latest turns; Spotlight filters by keyword.")
        options: [
            {
                label: root.tr("Spotlight"),
                value: "spotlight"
            },
            {
                label: root.tr("Tiles"),
                value: "tiles"
            }
        ]
        defaultValue: "spotlight"
    }

    ToggleSetting {
        settingKey: "autoPopup"
        label: root.tr("Pop up for permissions and questions")
        description: root.tr("Off: the widget only changes colour, and you click it to respond.")
        defaultValue: true
    }

    ToggleSetting {
        settingKey: "showLabel"
        label: root.tr("Show status text on the bar")
        defaultValue: true
    }
}
