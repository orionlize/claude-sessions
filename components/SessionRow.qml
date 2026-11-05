import QtQuick
import qs.Common
import qs.DCommon.Widgets
import "../lib/Phase.js" as Phase

Rectangle {
    id: root

    required property var modelData
    readonly property string status: modelData.status
    readonly property string phase: modelData.phase

    signal activated(var session)

    function tr(text) {
        return I18n.trFor("claudeSessions", text);
    }

    readonly property color statusColor: Phase.color(Theme, phase)
    readonly property string statusText: tr(Phase.label(phase))
    readonly property string detailText: Phase.detail(modelData)

    implicitHeight: content.implicitHeight + Theme.spacingS * 2
    radius: Theme.cornerRadius
    color: rowMouse.pressed ? Theme.primaryPressed : rowMouse.containsMouse ? Theme.primaryHover : Theme.primaryHoverLight

    MouseArea {
        id: rowMouse

        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.activated(root.modelData)
    }

    Row {
        id: content

        x: Theme.spacingM
        y: Theme.spacingS
        width: parent.width - Theme.spacingM * 2
        spacing: Theme.spacingS

        Rectangle {
            width: 8
            height: 8
            radius: 4
            anchors.verticalCenter: parent.verticalCenter
            color: root.statusColor
        }

        Column {
            width: parent.width - 8 - Theme.spacingS
            spacing: 2

            Item {
                width: parent.width
                implicitHeight: projectName.implicitHeight

                StyledText {
                    id: projectName

                    width: parent.width - statusLabel.implicitWidth - Theme.spacingS
                    text: Phase.name(root.modelData)
                    font.weight: Theme.fontWeightMedium
                    color: Theme.surfaceText
                    elide: Text.ElideRight
                    wrapMode: Text.NoWrap
                }

                StyledText {
                    id: statusLabel

                    anchors.right: parent.right
                    text: root.statusText
                    font.pixelSize: Theme.fontSizeSmall
                    color: root.statusColor
                }
            }

            StyledText {
                width: parent.width
                visible: text.length > 0
                text: root.detailText
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.surfaceVariantText
                elide: Text.ElideRight
                wrapMode: Text.NoWrap
            }
        }
    }
}
