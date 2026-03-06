"""
Vyuhaa Remote Client — Main Window
Entry point. Wires all pages, top/bottom bars, and AppState together.
"""

import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QStackedWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from styles import APP_STYLE
from api.app_state import AppState
from api.api_client import RelayClient
from widgets.topbar import TopBar
from widgets.bottombar import BottomBar
from pages.home_page import HomePage
from pages.connect_page import ConnectPage
from pages.live_page import LivePage
from pages.scan_page import ScanPage
from pages.files_page import FilesPage
from pages.settings_page import SettingsPage


SCREEN_INDEX = {
    "home":     0,
    "connect":  1,
    "live":     2,
    "scan":     3,
    "files":    4,
    "settings": 5,
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vyuhaa Remote Client")
        self.resize(1280, 800)
        self.setMinimumSize(960, 640)

        # ── Core state + relay client ─────────────────────────────────────
        self.state  = AppState(self)
        self.client = RelayClient(self.state, self)

        # ── Root layout ───────────────────────────────────────────────────
        root = QWidget(); self.setCentralWidget(root)
        v = QVBoxLayout(root); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)

        # TopBar
        self.topbar = TopBar()
        v.addWidget(self.topbar)

        # Stacked pages
        self.stack = QStackedWidget()
        self.home_page     = HomePage()
        self.connect_page  = ConnectPage()
        self.live_page     = LivePage()
        self.scan_page     = ScanPage()
        self.files_page    = FilesPage()
        self.settings_page = SettingsPage()

        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.connect_page)
        self.stack.addWidget(self.live_page)
        self.stack.addWidget(self.scan_page)
        self.stack.addWidget(self.files_page)
        self.stack.addWidget(self.settings_page)
        v.addWidget(self.stack, stretch=1)

        # BottomBar
        self.bottombar = BottomBar()
        v.addWidget(self.bottombar)

        # ── Wire signals ──────────────────────────────────────────────────
        self._wire_navigation()
        self._wire_state()
        self._wire_pages()

    # ── Navigation ────────────────────────────────────────────────────────

    def _navigate(self, screen: str):
        idx = SCREEN_INDEX.get(screen, 0)
        self.stack.setCurrentIndex(idx)
        self.bottombar.set_screen(screen)

    def _wire_navigation(self):
        self.home_page.navigate.connect(self._navigate)
        self.bottombar.home_clicked.connect(lambda: self._navigate("home"))
        self.connect_page.connect_requested.connect(self._on_connect)
        self.connect_page.disconnect_requested.connect(self._on_disconnect)
        self.live_page.end_session.connect(lambda: self._navigate("home"))

    # ── State → UI ────────────────────────────────────────────────────────

    def _wire_state(self):
        s = self.state
        s.relay_state_changed.connect(self._on_relay_state)
        s.device_state_changed.connect(self._on_device_state)
        s.latency_updated.connect(self.topbar.update_latency)
        s.log_message.connect(self.connect_page.update_log)
        s.position_changed.connect(self.live_page.update_position)
        s.focus_updated.connect(
            lambda score, label: self.live_page.update_focus(score / 1000.0, label)
        )
        s.scan_progress_changed.connect(self.scan_page.update_progress)
        s.frame_received.connect(self.live_page.camera.set_frame)

    def _on_relay_state(self, state: str):
        self.topbar.update_relay(state, self.state.relay_url)
        if state == "connecting":
            self.connect_page.set_relay_connecting()
        elif state == "connected":
            self.connect_page.set_relay_connected()
        elif state in ("off", "disconnected"):
            self.connect_page.set_disconnected()

    def _on_device_state(self, state: str):
        self.topbar.update_device(state)
        if state == "live":
            self.connect_page.set_live()
            self._navigate("live")  # auto-switch to Live View

    # ── Page → client ──────────────────────────────────────────────────────

    def _wire_pages(self):
        # Live page → client
        self.live_page.move_requested.connect(
            lambda axis, direction: self.client.send_move(axis, direction)
        )
        self.live_page.autofocus_requested.connect(self.client.send_autofocus)
        self.live_page.zero_requested.connect(self.state.zero_coords)
        self.live_page.capture_requested.connect(self.client.send_capture)
        self.live_page.stream_toggled.connect(self.client.send_stream_toggle)
        self.live_page.quality_changed.connect(self.client.send_quality)

        # Scan page → client
        self.scan_page.scan_start_requested.connect(
            lambda cols, rows, ov, pat, lbl, obj: self.client.start_scan()
        )
        self.scan_page.scan_pause_requested.connect(self.client.pause_scan)
        self.scan_page.scan_resume_requested.connect(self.client.pause_scan)  # toggles
        self.scan_page.scan_cancel_requested.connect(self.client.stop_scan)

        # Update connect page labels when relay/room change
        self.connect_page.update_relay_url_label(self.state.relay_url)
        self.connect_page.update_device_label(self.state.relay_room)

    # ── Connect / disconnect ───────────────────────────────────────────────

    def _on_connect(self, url: str, room: str, key: str, auto: bool):
        self.state.relay_url      = url
        self.state.relay_room     = room
        self.state.relay_key      = key
        self.state.auto_reconnect = auto
        self.connect_page.update_relay_url_label(url)
        self.connect_page.update_device_label(room)
        self.client.connect()

    def _on_disconnect(self):
        self.client.disconnect()

    # ── Keyboard shortcuts ─────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        """WASD stage movement and +/- focus when on Live page."""
        if self.stack.currentIndex() != SCREEN_INDEX["live"]:
            super().keyPressEvent(event)
            return

        key = event.key()
        step_map = {
            Qt.Key_W: ("y",  1),
            Qt.Key_S: ("y", -1),
            Qt.Key_A: ("x", -1),
            Qt.Key_D: ("x",  1),
            Qt.Key_Plus:  ("z",  1),
            Qt.Key_Equal: ("z",  1),   # unshifted +
            Qt.Key_Minus: ("z", -1),
        }
        if key in step_map:
            axis, direction = step_map[key]
            self.client.send_move(axis, direction)
        elif key == Qt.Key_Space:
            self.client.send_capture()
        else:
            super().keyPressEvent(event)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
