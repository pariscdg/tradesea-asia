import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

Window {
    id: win
    objectName: "tradeSeaWindow"
    width: 900; height: 740
    minimumWidth: 700; minimumHeight: 600
    visible: true
    title: "TradeSea · Automated Lockout"
    color: "transparent"
    flags: Qt.Window | Qt.FramelessWindowHint
    property var s: panelController.state
    property bool poolOpen: s.preview
    property bool settingsOpen: false
    property bool permitClose: false
    property bool refreshInteractive: false
    property int dragCount: 0
    property string pendingAction: ""
    readonly property bool maximized: visibility === Window.Maximized
    readonly property color muted: "#a8a2bf"
    function members(category) {
        return s.accounts.filter(function(a) { return (a.category || "none") === category; });
    }
    function requestRefresh(interactive) {
        refreshInteractive = interactive;
        if (s.dirty) { pendingAction = "refresh"; confirmDialog.open(); }
        else panelController.refresh(interactive);
    }
    function toggleMaximize() { if (maximized) showNormal(); else showMaximized(); }
    onClosing: function(close) {
        if (s.busy) { close.accepted = false; busyDialog.open(); }
        else if (s.dirty && !permitClose) { close.accepted = false; pendingAction = "close"; confirmDialog.open(); }
    }
    Component.onCompleted: panelController.start()

    component GlassButton: Button {
        id: button
        property bool primary: false
        implicitHeight: 38
        implicitWidth: Math.max(80, label.implicitWidth + 28)
        padding: 10
        opacity: enabled ? 1 : 0.4
        contentItem: Text {
            id: label
            text: button.text; color: button.primary ? "#2a2240" : "#f0ecff"
            font.pixelSize: 12; font.weight: button.primary ? Font.DemiBold : Font.Medium
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 11
            color: button.primary ? (button.hovered ? "#e6dfff" : "#c5b7f0") : (button.hovered ? "#20ffffff" : "#0bffffff")
            border.color: button.activeFocus ? "#c9baff" : (button.primary ? "#eadfff" : "#25ffffff")
            border.width: button.activeFocus ? 2 : 1
        }
    }

    component WindowButton: Button {
        id: wb
        property string kind
        implicitWidth: 34; implicitHeight: 30
        Accessible.name: kind === "min" ? "Minimize" : kind === "max" ? (win.maximized ? "Restore" : "Maximize") : "Close"
        ToolTip.visible: hovered
        ToolTip.text: Accessible.name
        background: Rectangle { radius: 8; color: wb.hovered ? (wb.kind === "close" ? "#c94e67" : "#20ffffff") : "transparent"; border.color: wb.activeFocus ? "#c9baff" : "transparent" }
        contentItem: Canvas {
            onPaint: {
                var c=getContext("2d"); c.reset(); c.strokeStyle="#e5dff2"; c.lineWidth=1.3;
                var x=width/2-5, y=height/2-5;
                if(wb.kind==="min") { c.beginPath(); c.moveTo(x,y+9); c.lineTo(x+10,y+9); c.stroke(); }
                else if(wb.kind==="max") { c.strokeRect(x,y,10,10); }
                else { c.beginPath(); c.moveTo(x,y); c.lineTo(x+10,y+10); c.moveTo(x+10,y); c.lineTo(x,y+10); c.stroke(); }
            }
        }
        onClicked: { if(kind==="min") win.showMinimized(); else if(kind==="max") win.toggleMaximize(); else win.close(); }
    }

    Rectangle {
        id: glass
        objectName: "glassSurface"
        anchors.fill: parent
        radius: win.maximized ? 0 : 28
        antialiasing: true
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: "#303049" }
            GradientStop { position: 0.55; color: "#242738" }
            GradientStop { position: 1; color: "#182d36" }
        }
        border.color: "#38d1c5f0"; border.width: 1
        // This is the only painted outer surface. The native Window stays transparent.
    }

    MouseArea {
        objectName: "windowDragStrip"
        x: 28; y: 0; width: parent.width - 170; height: 43
        onPressed: win.startSystemMove()
        onDoubleClicked: win.toggleMaximize()
    }
    Row {
        anchors.top: parent.top; anchors.right: parent.right
        anchors.topMargin: 7; anchors.rightMargin: 15; spacing: 3
        WindowButton { kind: "min"; objectName: "minimizeButton" }
        WindowButton { kind: "max"; objectName: "maximizeButton" }
        WindowButton { kind: "close"; objectName: "closeButton" }
    }

    ScrollView {
        id: scroll
        anchors.fill: parent
        anchors.leftMargin: 28; anchors.rightMargin: 28
        anchors.topMargin: 52; anchors.bottomMargin: 24
        contentWidth: availableWidth
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
            width: 6
            background: Item {}
            contentItem: Rectangle { implicitWidth: 4; radius: 2; color: parent.pressed ? "#a89ac9" : "#606d6683" }
        }
        ColumnLayout {
            width: scroll.availableWidth
            spacing: 0
            Label {
                visible: s.preview
                text: "INTERACTIVE PREVIEW · SAMPLE ACCOUNTS"
                color: "#b8aadd"; font.pixelSize: 9; font.letterSpacing: 2
                Layout.alignment: Qt.AlignHCenter; Layout.bottomMargin: 20
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 20
                ColumnLayout {
                    spacing: 8
                    Label { text: "◈  T R A D E S E A"; color: "#c1b6df"; font.pixelSize: 10 }
                    Label { text: "Automated Lockout"; color: "#f4f2ff"; font.pixelSize: win.width < 750 ? 23 : 27; font.weight: Font.DemiBold }
                }
                Item { Layout.fillWidth: true }
                GlassButton { text: "Sign in ↗"; enabled: !s.busy; onClicked: win.requestRefresh(true) }
                GlassButton { text: "↻  Refresh"; enabled: !s.busy; onClicked: win.requestRefresh(false) }
            }
            RowLayout {
                Layout.fillWidth: true; Layout.topMargin: 22; Layout.bottomMargin: 24; spacing: 8
                Rectangle { width: 6; height: 6; radius: 3; color: s.loaded ? "#87dac5" : "#a7a0bd" }
                Label { text: s.connection; color: win.muted; font.pixelSize: 12 }
                Item { Layout.fillWidth: true }
                Label { text: s.schedule; color: win.muted; font.pixelSize: 11; elide: Text.ElideRight; Layout.maximumWidth: win.width * 0.45 }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 18
                CategoryZone { category: "asia"; heading: "Asia"; glyph: "☾"; subtitle: (s.duration / 3600) + "-hour automated lockout"; Layout.fillWidth: true; Layout.preferredWidth: 1 }
                CategoryZone { category: "day"; heading: "24-hour"; glyph: "◷"; subtitle: "Full-day automated lockout"; Layout.fillWidth: true; Layout.preferredWidth: 1 }
            }
            Rectangle {
                id: unallocated
                Layout.fillWidth: true; Layout.topMargin: 18
                implicitHeight: 52 + (win.poolOpen ? poolColumn.implicitHeight + 14 : 0)
                radius: 16; color: poolDrop.containsDrag ? "#28b9abff" : "#1810121f"
                border.color: poolDrop.containsDrag ? "#b9abff" : "#25ffffff"
                DropArea {
                    id: poolDrop; anchors.fill: parent; keys: ["account"]
                    onDropped: function(drop) { var key = drop.source.accountKey; Qt.callLater(function(){ panelController.moveAccount(key,"none"); }); drop.acceptProposedAction(); }
                }
                Button {
                    width: parent.width; height: 52; flat: true
                    Accessible.name: "Unallocated accounts"
                    background: Rectangle { color: "transparent"; radius: 16; border.color: parent.activeFocus ? "#b9abff" : "transparent" }
                    contentItem: RowLayout {
                        anchors.fill: parent; anchors.margins: 16
                        Label { text: win.poolOpen ? "⌄" : "›"; color: win.muted }
                        Label { text: "Unallocated accounts"; color: "#eee9fc"; font.pixelSize: 12 }
                        Label { text: win.members("none").length; color: win.muted; font.pixelSize: 11; Layout.leftMargin: 8 }
                        Item { Layout.fillWidth: true }
                        Label { text: win.poolOpen ? "Drag into a category" : "Expand to allocate"; color: "#8e88a4"; font.pixelSize: 10 }
                    }
                    onClicked: win.poolOpen = !win.poolOpen
                }
                Flow {
                    id: poolColumn
                    x: 14; y: 52; width: parent.width - 28; spacing: 8
                    visible: win.poolOpen
                    Repeater { model: win.members("none"); AccountTile { required property var modelData; account: modelData; width: (poolColumn.width-8)/2 } }
                    Label { visible: win.members("none").length===0; width: parent.width; height: 38; text: "All accounts allocated. Drop here to unallocate."; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; color: win.muted; font.pixelSize: 11 }
                }
            }
            Rectangle {
                visible: win.settingsOpen
                Layout.fillWidth: true; Layout.topMargin: 16
                implicitHeight: settingsColumn.implicitHeight + 30
                radius: 14; color: "#1010121f"; border.color: "#28ffffff"
                ColumnLayout {
                    id: settingsColumn; x: 16; y: 15; width: parent.width-32; spacing: 12
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "Asia lockout duration"; color: "#d1c9e3"; font.pixelSize: 12; Layout.fillWidth: true }
                        ComboBox {
                            id: durationBox
                            objectName: "durationControl"
                            enabled: !s.busy && s.loaded
                            model: ["1 hour","2 hours","4 hours","6 hours","8 hours","12 hours","24 hours"]
                            currentIndex: [3600,7200,14400,21600,28800,43200,86400].indexOf(s.duration)
                            onActivated: { panelController.setDuration([3600,7200,14400,21600,28800,43200,86400][index]); currentIndex = Qt.binding(function(){return [3600,7200,14400,21600,28800,43200,86400].indexOf(s.duration);}); }
                        }
                    }
                    Label { Layout.fillWidth: true; text: "Both categories use the existing Sun–Thu, 5:00 PM system-local schedule. Active lockout deadlines stay fixed. Unallocated accounts are excluded from future runs."; wrapMode: Text.WordWrap; color: win.muted; font.pixelSize: 11 }
                }
            }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 24; Layout.bottomMargin: 22; height: 1; color: "#20ffffff" }
            RowLayout {
                Layout.fillWidth: true; spacing: 16
                GlassButton { objectName: "saveButton"; text: "Save changes"; primary: true; implicitHeight: 43; enabled: s.loaded && !s.busy; onClicked: panelController.save() }
                ColumnLayout {
                    spacing: 6
                    Label { text: s.loaded ? s.allocated + " accounts allocated" + (s.dirty ? " · Unsaved" : "") : "Loading accounts…"; color: "#ddd6ec"; font.pixelSize: 11 }
                    Label { text: "Drag to allocate · Changes apply after saving."; color: win.muted; font.pixelSize: 10 }
                }
                Item { Layout.fillWidth: true }
                GlassButton { text: "⚙"; implicitWidth: 40; Accessible.name: "Settings"; onClicked: win.settingsOpen = !win.settingsOpen }
            }
            Label { Layout.fillWidth: true; Layout.topMargin: 16; text: s.message; color: s.error ? "#ffb9ac" : "#aaa2bc"; font.pixelSize: 11; wrapMode: Text.WordWrap; Accessible.role: Accessible.StaticText }
        }
    }

    component CategoryZone: Rectangle {
        id: zone
        objectName: "zone-" + category
        required property string category
        required property string heading
        required property string glyph
        required property string subtitle
        property var rows: win.members(category)
        implicitHeight: Math.max(248, tiles.implicitHeight + 104)
        Layout.alignment: Qt.AlignTop
        radius: 20
        color: zoneDrop.containsDrag ? "#25b9abff" : "#08c6baff"
        border.color: zoneDrop.containsDrag ? "#b9abff" : "#25ffffff"
        DropArea {
            id: zoneDrop; anchors.fill: parent; keys: ["account"]
            onDropped: function(drop) { var key=drop.source.accountKey; var dest=zone.category; Qt.callLater(function(){panelController.moveAccount(key,dest);}); drop.acceptProposedAction(); }
        }
        RowLayout {
            x: 17; y: 20; width: parent.width-34; spacing: 10
            Rectangle {
                width: 32; height: 32; radius: 11; color: "#20b6a3ef"
                Label { anchors.centerIn: parent; text: zone.glyph; color: zone.category === "asia" ? "#ccbdff" : "#a4d9e5"; font.pixelSize: 23 }
            }
            Label { text: zone.heading; color: "#f2eeff"; font.pixelSize: 22; font.weight: Font.DemiBold }
            Item { Layout.fillWidth: true }
            Label { text: zone.rows.length; color: win.muted; font.pixelSize: 11 }
        }
        Label { x: 59; y: 59; text: zone.subtitle; color: win.muted; font.pixelSize: 11 }
        Column {
            id: tiles; x: 16; y: 91; width: parent.width-32; spacing: 8
            Repeater { model: zone.rows; AccountTile { required property var modelData; account: modelData; width: tiles.width } }
            Rectangle {
                visible: zone.rows.length===0; width: parent.width; height: 116; radius: 12; color: "transparent"; border.color: "#15ffffff"
                Label { anchors.centerIn: parent; text: "+\nDrop accounts here"; lineHeight: 1.6; horizontalAlignment: Text.AlignHCenter; color: "#928aa8"; font.pixelSize: 12 }
            }
        }
    }

    component AccountTile: Item {
        id: slot
        required property var account
        height: 57
        Rectangle {
            id: tile
            objectName: "account-" + slot.account.key
            property string accountKey: slot.account.key
            width: mouse.drag.active ? Math.min(350, slot.width) : slot.width; height: 57; radius: 12
            color: mouse.drag.active ? "#4b4267" : "#12ffffff"
            border.color: mouse.drag.active ? "#c1aff4" : "#30ffffff"
            Drag.active: mouse.drag.active
            Drag.source: tile
            Drag.keys: ["account"]
            Drag.hotSpot.x: width/2; Drag.hotSpot.y: height/2
            Drag.supportedActions: Qt.MoveAction
            states: State {
                when: mouse.drag.active
                ParentChange { target: tile; parent: dragOverlay }
                PropertyChanges { target: tile; z: 100 }
            }
            MouseArea {
                id: mouse; anchors.fill: parent; drag.target: tile
                drag.minimumX: 0; drag.maximumX: win.width - tile.width
                drag.minimumY: 0; drag.maximumY: win.height - tile.height
                enabled: s.loaded && !s.busy
                cursorShape: drag.active ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                onReleased: tile.Drag.drop()
            }
            Label { x: 11; anchors.verticalCenter: parent.verticalCenter; text: "⠿"; color: "#9285ac"; font.pixelSize: 20 }
            Column {
                x: 34; anchors.verticalCenter: parent.verticalCenter; width: parent.width-73; spacing: 4
                Label { width: parent.width; text: slot.account.name; elide: Text.ElideMiddle; color: "#eee9fa"; font.pixelSize: 12; font.weight: Font.DemiBold }
                Label { width: parent.width; text: slot.account.statusText; elide: Text.ElideRight; color: slot.account.restricted ? "#dfc393" : "#a49bb7"; font.pixelSize: 10 }
            }
            Button {
                id: moveButton; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; anchors.rightMargin: 5
                width: 29; height: 35; enabled: s.loaded && !s.busy
                Accessible.name: "Move " + slot.account.name
                contentItem: Label { text: "⌄"; color: "#c8bddb"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { radius: 7; color: moveButton.hovered ? "#18ffffff" : "transparent"; border.color: moveButton.activeFocus ? "#bcabf6" : "transparent" }
                onClicked: accountMenu.popup()
                Menu {
                    id: accountMenu
                    MenuItem { text: "Asia"; onTriggered: panelController.moveAccount(slot.account.key,"asia") }
                    MenuItem { text: "24-hour"; onTriggered: panelController.moveAccount(slot.account.key,"day") }
                    MenuItem { text: "Unallocated"; onTriggered: panelController.moveAccount(slot.account.key,"none") }
                }
            }
        }
    }
    Item { id: dragOverlay; anchors.fill: parent; z: 100 }

    Dialog {
        id: confirmDialog
        anchors.centerIn: parent; width: Math.min(430,win.width-60)
        modal: true; title: "Unsaved allocations"
        standardButtons: Dialog.Discard | Dialog.Cancel
        Label { width: parent.width; text: win.pendingAction === "close" ? "Close without saving your allocation changes?" : "Discard your changes and refresh accounts?"; wrapMode: Text.WordWrap }
        onDiscarded: { if(win.pendingAction==="close"){win.permitClose=true;win.close();} else panelController.refresh(win.refreshInteractive); }
    }
    Dialog {
        id: busyDialog; anchors.centerIn: parent; width: Math.min(430,win.width-60)
        modal: true; title: "Operation in progress"; standardButtons: Dialog.Ok
        Label { width: parent.width; text: "Wait for the current operation to finish before closing."; wrapMode: Text.WordWrap }
    }
    // Native bottom-right resizing, inset from the transparent corner.
    MouseArea { x: win.width-26; y: win.height-26; width: 16; height: 16; visible: !win.maximized; cursorShape: Qt.SizeFDiagCursor; onPressed: win.startSystemResize(Qt.RightEdge | Qt.BottomEdge) }
}
