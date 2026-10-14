// Standalone Frametop Extension Manager, intentionally NOT compiled into core.
import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    title: "Frametop Extensions"
    width: Kirigami.Units.gridUnit * 48
    height: Kirigami.Units.gridUnit * 37

    property string selectedPlugin: ""
    property string selectedSource: ""
    property string selectedRepo: ""

    pageStack.initialPage: browsePage

    function navigate(page) {
        pageStack.clear()
        pageStack.push(page)
    }

    header: Controls.TabBar {
        id: tabs
        Controls.TabButton {
            text: "Browse"
            icon.name: "applications-other"
            onClicked: root.navigate(browsePage)
        }
        Controls.TabButton {
            text: "Installed"
            icon.name: "package-installed-updated"
            onClicked: root.navigate(installedPage)
        }
        Controls.TabButton {
            text: "Repositories"
            icon.name: "vcs-branch"
            onClicked: root.navigate(repositoriesPage)
        }
    }

    Connections {
        target: backend
        function onMessage(message, isError) {
            root.showPassiveNotification(message, isError ? "long" : "short")
        }
    }

    Controls.Dialog {
        id: installDialog
        modal: true
        parent: Controls.Overlay.overlay
        anchors.centerIn: parent
        title: "Install extension"
        width: Math.min(root.width * 0.82, Kirigami.Units.gridUnit * 37)
        standardButtons: Controls.Dialog.Ok | Controls.Dialog.Cancel
        contentItem: Controls.Label {
            width: installDialog.width - 60
            text: backend.installPlan(root.selectedPlugin, root.selectedSource)
            wrapMode: Text.Wrap
        }
        onAccepted: backend.install(root.selectedPlugin, root.selectedSource)
    }

    Controls.Dialog {
        id: uninstallDialog
        modal: true
        parent: Controls.Overlay.overlay
        anchors.centerIn: parent
        title: "Remove extension?"
        standardButtons: Controls.Dialog.Yes | Controls.Dialog.Cancel
        contentItem: Controls.Label {
            text: "Remove " + root.selectedPlugin + " from your installed extensions?\n" +
                  "No extension entrypoint or uninstall script will be run."
            wrapMode: Text.Wrap
        }
        onAccepted: backend.uninstall(root.selectedPlugin)
    }

    Controls.Dialog {
        id: removeRepoDialog
        modal: true
        parent: Controls.Overlay.overlay
        anchors.centerIn: parent
        title: "Remove repository?"
        standardButtons: Controls.Dialog.Yes | Controls.Dialog.Cancel
        contentItem: Controls.Label {
            text: "Remove " + root.selectedRepo + " from the catalog?\n" +
                  "Already installed extensions will be retained."
            wrapMode: Text.Wrap
        }
        onAccepted: backend.removeSource(root.selectedRepo)
    }

    Controls.Dialog {
        id: addRepoDialog
        modal: true
        parent: Controls.Overlay.overlay
        anchors.centerIn: parent
        title: "Add GitHub repository"
        width: Math.min(root.width * 0.82, Kirigami.Units.gridUnit * 34)
        standardButtons: Controls.Dialog.Ok | Controls.Dialog.Cancel
        ColumnLayout {
            width: addRepoDialog.width - 50
            Controls.Label {
                text: "Only add repositories whose maintainers you trust. " +
                      "Extensions may contain arbitrary executable code."
                Layout.fillWidth: true
                wrapMode: Text.Wrap
            }
            Controls.TextField {
                id: repoField
                Layout.fillWidth: true
                placeholderText: "https://github.com/owner/repository"
                onAccepted: addRepoDialog.accept()
            }
            Controls.Label {
                text: "GitHub HTTPS and SSH (git@github.com:owner/repo.git) are supported."
                color: Kirigami.Theme.disabledTextColor
                Layout.fillWidth: true
                wrapMode: Text.Wrap
            }
        }
        onAccepted: backend.addSource(repoField.text.trim())
    }

    Component {
        id: browsePage
        Kirigami.ScrollablePage {
            title: "Browse extensions"
            ColumnLayout {
                width: parent.width
                spacing: Kirigami.Units.largeSpacing

                Controls.Label {
                    Layout.fillWidth: true
                    text: "Our extensions catalog is included by default. Add other GitHub repositories " +
                          "under Repositories. Nothing installs or runs without your action."
                    wrapMode: Text.Wrap
                }
                Controls.BusyIndicator {
                    running: backend.busy
                    visible: backend.busy
                    Layout.alignment: Qt.AlignHCenter
                }
                Repeater {
                    model: backend.catalog
                    delegate: Controls.Frame {
                        required property var modelData
                        Layout.fillWidth: true
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: Kirigami.Units.smallSpacing
                            RowLayout {
                                Layout.fillWidth: true
                                Controls.Label {
                                    text: modelData.name + "   v" + modelData.version
                                    font.bold: true
                                    Layout.fillWidth: true
                                }
                                Controls.Label {
                                    text: modelData.status
                                    color: Kirigami.Theme.disabledTextColor
                                }
                            }
                            Controls.Label {
                                text: modelData.description
                                Layout.fillWidth: true
                                wrapMode: Text.Wrap
                            }
                            Controls.Label {
                                text: "Source: " + modelData.repository +
                                      "    API: " + modelData.compatibility
                                Layout.fillWidth: true
                                color: Kirigami.Theme.disabledTextColor
                                wrapMode: Text.Wrap
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Controls.Label {
                                    text: modelData.installed
                                          ? "Installed v" + modelData.installed_version +
                                            (modelData.enabled ? " · selected" : "")
                                          : "Not installed"
                                    Layout.fillWidth: true
                                }
                                Controls.Button {
                                    text: modelData.installed
                                          ? (modelData.updateAvailable ? "Update" : "Reinstall")
                                          : "Install"
                                    icon.name: modelData.installed ? "view-refresh" : "download"
                                    enabled: !backend.busy
                                    onClicked: {
                                        root.selectedPlugin = modelData.id
                                        root.selectedSource = modelData.source
                                        installDialog.open()
                                    }
                                }
                            }
                        }
                    }
                }
                Controls.Label {
                    visible: backend.catalog.length === 0
                    text: "No extensions found. Check your repository sources."
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                }
            }
        }
    }

    Component {
        id: installedPage
        Kirigami.ScrollablePage {
            title: "Installed extensions"
            ColumnLayout {
                width: parent.width
                spacing: Kirigami.Units.largeSpacing

                Controls.Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: "Installed extensions are isolated snapshots. Enabled is currently only a " +
                          "manager selection flag. It does NOT launch processes or install services."
                }
                Repeater {
                    model: backend.installed
                    delegate: Controls.Frame {
                        required property var modelData
                        Layout.fillWidth: true
                        RowLayout {
                            anchors.fill: parent
                            spacing: Kirigami.Units.smallSpacing
                            ColumnLayout {
                                Layout.fillWidth: true
                                Controls.Label {
                                    text: modelData.id
                                    font.bold: true
                                }
                                Controls.Label {
                                    text: "Version " + modelData.version + " · " + modelData.source
                                    color: Kirigami.Theme.disabledTextColor
                                }
                            }
                            Controls.Switch {
                                text: "Selected"
                                checked: modelData.enabled
                                enabled: !backend.busy
                                onToggled: backend.setEnabled(modelData.id, checked)
                            }
                            Controls.Button {
                                text: "Remove"
                                icon.name: "edit-delete"
                                enabled: !backend.busy
                                onClicked: {
                                    root.selectedPlugin = modelData.id
                                    uninstallDialog.open()
                                }
                            }
                        }
                    }
                }
                Controls.Label {
                    visible: backend.installed.length === 0
                    text: "No installed extensions yet."
                }
            }
        }
    }

    Component {
        id: repositoriesPage
        Kirigami.ScrollablePage {
            title: "Repository sources"
            ColumnLayout {
                width: parent.width
                spacing: Kirigami.Units.largeSpacing

                RowLayout {
                    Layout.fillWidth: true
                    Controls.Label {
                        text: "Extension repositories"
                        font.bold: true
                        Layout.fillWidth: true
                    }
                    Controls.Button {
                        text: "Add repository"
                        icon.name: "list-add"
                        enabled: !backend.busy
                        onClicked: addRepoDialog.open()
                    }
                }
                Controls.Label {
                    Layout.fillWidth: true
                    text: "Refresh explicitly pulls the latest revision. The built-in source is " +
                          "your existing local Git checkout and keeps its SSH deploy-key settings."
                    wrapMode: Text.Wrap
                }
                Repeater {
                    model: backend.sources
                    delegate: Controls.Frame {
                        required property var modelData
                        Layout.fillWidth: true
                        ColumnLayout {
                            anchors.fill: parent
                            Controls.Label {
                                text: modelData.name + (modelData.builtin ? " (built-in)" : "")
                                font.bold: true
                            }
                            Controls.Label {
                                text: modelData.url
                                Layout.fillWidth: true
                                wrapMode: Text.WrapAnywhere
                                color: Kirigami.Theme.disabledTextColor
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Controls.Label {
                                    text: modelData.path
                                    Layout.fillWidth: true
                                    wrapMode: Text.WrapAnywhere
                                    color: Kirigami.Theme.disabledTextColor
                                }
                                Controls.Button {
                                    text: "Refresh"
                                    icon.name: "view-refresh"
                                    enabled: !backend.busy
                                    onClicked: backend.refreshSource(modelData.id)
                                }
                                Controls.Button {
                                    text: "Remove"
                                    visible: !modelData.builtin
                                    enabled: !backend.busy
                                    onClicked: {
                                        root.selectedRepo = modelData.id
                                        removeRepoDialog.open()
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
