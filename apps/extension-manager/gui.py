#!/usr/bin/env python3
"""Frametop Extension Manager desktop application (PySide6 + Kirigami)."""
from __future__ import annotations

from pathlib import Path
import sys
import threading

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sdk"))
from frametop_ext import Frametop  # noqa: E402
from manager_core import Manager, ManagerError  # noqa: E402


class Backend(QObject):
    changed = Signal()
    busyChanged = Signal()
    message = Signal(str, bool)
    _completed = Signal(str, bool)

    def __init__(self):
        super().__init__()
        self.manager = Manager(client=Frametop())
        self._catalog = []
        self._sources = []
        self._installed = {}
        self._busy = False
        self._completed.connect(self._finish)
        self.reload()

    @Property("QVariantList", notify=changed)
    def catalog(self):
        return self._catalog

    @Property("QVariantList", notify=changed)
    def sources(self):
        return self._sources

    @Property("QVariantList", notify=changed)
    def installed(self):
        return [
            {"id": key, "version": value["version"], "source": value["source"],
             "enabled": value["enabled"]}
            for key, value in sorted(self._installed.items())
        ]

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    def reload(self):
        try:
            self._sources = self.manager.sources()
            self._installed = self.manager.installed_items()
            self._catalog = self.manager.catalog()
            for item in self._catalog:
                item["compatibility"] = self.manager.compatibility(item)
                item["updateAvailable"] = bool(item["installed_version"] and
                                               item["installed_version"] != item["version"])
        except Exception as exc:
            self.message.emit(str(exc), True)
        self.changed.emit()

    def _work(self, callback, success):
        if self._busy:
            return
        self._busy = True
        self.busyChanged.emit()

        def run():
            try:
                callback()
                self._completed.emit(success, False)
            except Exception as exc:
                self._completed.emit(str(exc), True)

        threading.Thread(target=run, daemon=True).start()

    @Slot(str, bool)
    def _finish(self, message, error):
        self._busy = False
        self.busyChanged.emit()
        self.reload()
        self.message.emit(message, error)

    @Slot()
    def refreshView(self):
        self.reload()

    @Slot(str, str, result=str)
    def installPlan(self, identity, source_id):
        try:
            options = [x for x in self._catalog if x["id"] == identity and
                       x["source"] == source_id]
            if len(options) != 1:
                return "No unique matching repository/plugin pair."
            target = options[0]
            chain = self.manager.plan(identity, source_id)
            return (
                "Install from " + target["repository"] + ":\n\n" +
                "\n".join(f"• {x['name']} v{x['version']} ({x['source']})" for x in chain) +
                "\n\nThis installs files into your home directory. It does NOT execute " +
                "or automatically start downloaded code. Review and trust third-party " +
                "repositories before choosing Install."
            )
        except Exception as exc:
            return str(exc)

    @Slot(str, str)
    def install(self, identity, source):
        self._work(lambda: self.manager.install(identity, source),
                   f"Installed {identity}. No plugin process started.")

    @Slot(str)
    def uninstall(self, identity):
        self._work(lambda: self.manager.uninstall(identity), f"Uninstalled {identity}")

    @Slot(str, bool)
    def setEnabled(self, identity, enabled):
        self._work(lambda: self.manager.enable(identity, enabled),
                   (f"Enabled {identity} (selection only; no autostart)" if enabled else
                    f"Disabled {identity}"))

    @Slot(str)
    def addSource(self, url):
        self._work(lambda: self.manager.add_source(url), "Repository added to catalog")

    @Slot(str)
    def refreshSource(self, source_id):
        self._work(lambda: self.manager.refresh(source_id), f"Refreshed {source_id}")

    @Slot(str)
    def removeSource(self, source_id):
        self._work(lambda: self.manager.remove_source(source_id),
                   f"Removed source {source_id}. Installed snapshots were retained.")


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Frametop Extension Manager")
    app.setDesktopFileName("frametop-extension-manager")
    app.setWindowIcon(QIcon.fromTheme("preferences-plugin"))
    QQuickStyle.setStyle("org.kde.desktop")
    engine = QQmlApplicationEngine()
    backend = Backend()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name("main.qml"))))
    if not engine.rootObjects():
        print("extension-manager: failed to load Kirigami UI", file=sys.stderr)
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
