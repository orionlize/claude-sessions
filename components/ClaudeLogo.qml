import QtQuick
import qs.DCommon.Widgets as D

// The Claude spark, tinted like a theme icon.
D.DSVGIcon {
    property color color: "#D97757"

    source: Qt.resolvedUrl("../assets/claude.svg")
    colorOverride: color
}
