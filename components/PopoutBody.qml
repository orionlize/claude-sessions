import QtQuick
import qs.Common
import qs.DCommon.Widgets

Column {
    id: root

    property var sessions: []
    property var requests: []
    readonly property var current: requests.length ? requests[0] : null
    readonly property bool engaged: hover.hovered || (requestCard.item?.textFocused ?? false)

    signal responded(string id, string action, var answers)
    signal sessionActivated(var session)

    function tr(text) {
        return I18n.trFor("claudeSessions", text);
    }

    spacing: Theme.spacingS

    HoverHandler {
        id: hover
    }

    Loader {
        id: requestCard

        width: parent.width
        active: root.current !== null
        visible: active
        sourceComponent: RequestCard {
            request: root.current
            pendingCount: root.requests.length
            onResponded: (id, action, answers) => root.responded(id, action, answers)
        }
    }

    StyledText {
        width: parent.width
        visible: root.sessions.length === 0
        text: root.tr("No Claude sessions")
        color: Theme.surfaceVariantText
        horizontalAlignment: Text.AlignHCenter
        topPadding: Theme.spacingM
        bottomPadding: Theme.spacingM
    }

    Repeater {
        model: root.sessions

        SessionRow {
            width: root.width
            onActivated: session => root.sessionActivated(session)
        }
    }
}
