import QtQuick
import qs.Common
import qs.DCommon.Widgets

Rectangle {
    id: root

    property var request: null
    property int pendingCount: 1
    property var selections: ({})
    property var customAnswers: ({})
    property int focusedFields: 0

    // Translucent primary layers: an opaque surface here would hide the popup's blur.
    readonly property color tint: Theme.primaryHoverLight
    readonly property color tintStrong: Theme.primaryPressed
    readonly property bool isQuestion: request?.kind === "question"
    readonly property var questions: request?.questions ?? []
    readonly property bool textFocused: focusedFields > 0
    readonly property bool complete: questions.every((q, i) => answerFor(q, i).length > 0)

    signal responded(string id, string action, var answers)

    function tr(text) {
        return I18n.trFor("claudeSessions", text);
    }

    function selectedLabels(index) {
        return selections[index] ?? [];
    }

    function toggle(question, index, label) {
        const current = selectedLabels(index);
        const next = Object.assign({}, selections);
        if (question.multiSelect)
            next[index] = current.includes(label) ? current.filter(l => l !== label) : current.concat([label]);
        else
            next[index] = [label];
        selections = next;
    }

    function setCustom(index, text) {
        const next = Object.assign({}, customAnswers);
        next[index] = text;
        customAnswers = next;
        if (!question(index).multiSelect && text.length > 0) {
            const cleared = Object.assign({}, selections);
            cleared[index] = [];
            selections = cleared;
        }
    }

    function question(index) {
        return questions[index];
    }

    function answerFor(q, index) {
        const custom = (customAnswers[index] ?? "").trim();
        const labels = selectedLabels(index);
        if (q.multiSelect)
            return labels.concat(custom ? [custom] : []).join(", ");
        return custom || labels[0] || "";
    }

    function collectAnswers() {
        const answers = {};
        questions.forEach((q, i) => answers[q.question] = answerFor(q, i));
        return answers;
    }

    function respond(action, answers) {
        responded(request.id, action, answers ?? null);
    }

    onRequestChanged: {
        selections = {};
        customAnswers = {};
        focusedFields = 0;
    }

    implicitHeight: body.implicitHeight + Theme.spacingM * 2
    radius: Theme.cornerRadius
    color: Theme.primaryHover
    border.width: 1
    border.color: Theme.primarySelected

    Column {
        id: body

        x: Theme.spacingM
        y: Theme.spacingM
        width: parent.width - Theme.spacingM * 2
        spacing: Theme.spacingS

        Row {
            width: parent.width
            spacing: Theme.spacingS

            DIcon {
                anchors.verticalCenter: parent.verticalCenter
                name: root.isQuestion ? "help" : "shield"
                size: Theme.iconSize - 4
                color: Theme.primary
            }

            StyledText {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - Theme.iconSize - Theme.spacingS * 2 - counter.implicitWidth
                text: (root.isQuestion ? root.tr("Claude is asking") : root.tr("Allow %1?").arg(root.request?.tool_name ?? "")) + " · " + (root.request?.project ?? "")
                font.weight: Theme.fontWeightMedium
                color: Theme.surfaceText
                elide: Text.ElideRight
                wrapMode: Text.NoWrap
            }

            StyledText {
                id: counter

                anchors.verticalCenter: parent.verticalCenter
                visible: root.pendingCount > 1
                text: "1/" + root.pendingCount
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.surfaceVariantText
            }
        }

        Rectangle {
            width: parent.width
            visible: !root.isQuestion
            height: Math.min(detailText.implicitHeight + Theme.spacingS * 2, 220)
            radius: Theme.cornerRadiusS ?? 8
            color: root.tint
            clip: true

            Flickable {
                anchors.fill: parent
                anchors.margins: Theme.spacingS
                contentHeight: detailText.implicitHeight
                boundsBehavior: Flickable.StopAtBounds

                TextEdit {
                    id: detailText

                    width: parent.width
                    readOnly: true
                    selectByMouse: true
                    text: root.request?.detail ?? ""
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.WrapAnywhere
                    color: Theme.surfaceText
                    font.family: Theme.monoFontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    // Ligatures would disguise what is being approved.
                    font.features: ({
                            "liga": 0,
                            "calt": 0
                        })
                }
            }
        }

        Repeater {
            model: root.isQuestion ? root.questions : []

            Column {
                id: questionBlock

                required property var modelData
                required property int index

                width: body.width
                spacing: Theme.spacingXS

                StyledText {
                    width: parent.width
                    text: questionBlock.modelData.question
                    wrapMode: Text.Wrap
                    color: Theme.surfaceText
                }

                Repeater {
                    model: questionBlock.modelData.options

                    Rectangle {
                        id: optionRow

                        required property var modelData
                        readonly property bool selected: root.selectedLabels(questionBlock.index).includes(modelData.label)

                        width: questionBlock.width
                        implicitHeight: optionColumn.implicitHeight + Theme.spacingS * 2
                        radius: Theme.cornerRadiusS ?? 8
                        color: selected ? Theme.primarySelected : optionArea.containsMouse ? root.tintStrong : root.tint
                        border.width: selected ? 1 : 0
                        border.color: Theme.primary

                        Row {
                            x: Theme.spacingS
                            y: Theme.spacingS
                            width: parent.width - Theme.spacingS * 2
                            spacing: Theme.spacingS

                            DIcon {
                                name: questionBlock.modelData.multiSelect ? (optionRow.selected ? "check_box" : "check_box_outline_blank") : (optionRow.selected ? "radio_button_checked" : "radio_button_unchecked")
                                size: Theme.iconSizeSmall + 2
                                color: optionRow.selected ? Theme.primary : Theme.surfaceVariantText
                            }

                            Column {
                                id: optionColumn

                                width: parent.width - Theme.iconSizeSmall - 2 - Theme.spacingS

                                StyledText {
                                    width: parent.width
                                    text: optionRow.modelData.label
                                    wrapMode: Text.Wrap
                                    color: Theme.surfaceText
                                }

                                StyledText {
                                    width: parent.width
                                    visible: text.length > 0
                                    text: optionRow.modelData.description ?? ""
                                    wrapMode: Text.Wrap
                                    font.pixelSize: Theme.fontSizeSmall
                                    color: Theme.surfaceVariantText
                                }
                            }
                        }

                        MouseArea {
                            id: optionArea

                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.toggle(questionBlock.modelData, questionBlock.index, optionRow.modelData.label)
                        }
                    }
                }

                DTextField {
                    width: parent.width
                    placeholderText: root.tr("Other…")
                    backgroundColor: root.tint
                    text: root.customAnswers[questionBlock.index] ?? ""
                    onTextEdited: root.setCustom(questionBlock.index, text)
                    onFocusStateChanged: hasFocus => root.focusedFields += hasFocus ? 1 : -1
                }
            }
        }

        Flow {
            width: parent.width
            spacing: Theme.spacingS
            layoutDirection: Qt.RightToLeft

            DButton {
                visible: !root.isQuestion
                text: root.tr("Allow")
                iconName: "check"
                backgroundColor: Theme.primary
                textColor: Theme.primaryText
                onClicked: root.respond("allow")
            }

            DButton {
                visible: root.isQuestion
                enabled: root.complete
                text: root.tr("Submit")
                iconName: "send"
                backgroundColor: Theme.primary
                textColor: Theme.primaryText
                onClicked: root.respond("answer", root.collectAnswers())
            }

            DButton {
                visible: !root.isQuestion && (root.request?.always_label ?? "") !== ""
                text: root.tr("Always allow")
                tooltipText: root.request?.always_label ?? ""
                backgroundColor: root.tintStrong
                textColor: Theme.surfaceText
                onClicked: root.respond("always")
            }

            DButton {
                text: root.isQuestion ? root.tr("Skip") : root.tr("Deny")
                iconName: "close"
                backgroundColor: root.tintStrong
                textColor: Theme.error
                onClicked: root.respond("deny")
            }
        }
    }
}
