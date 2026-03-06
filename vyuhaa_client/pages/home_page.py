"""
Vyuhaa Remote Client — Home Page
6-tile navigation grid matching vyuhaa-remote-client-v3.html
"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout,
                                QPushButton, QLabel, QSizePolicy)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont


class TileButton(QPushButton):
    """A single home-screen navigation tile."""

    def __init__(self, icon: str, label: str, variant: str = "default",
                 badge: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName(
            "HomeTileBtnFeatured" if variant == "featured"
            else "HomeTileBtnLive" if variant == "live"
            else "HomeTileBtn"
        )
        self.setFixedSize(180, 180)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(12)

        icon_lbl = QLabel(icon)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet(
            "font-size: 26px; background: transparent; border: none;"
        )

        name_lbl = QLabel(label)
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: #94a3b8; "
            "background: transparent; border: none; letter-spacing: 1px;"
        )

        layout.addWidget(icon_lbl)
        layout.addWidget(name_lbl)

        if badge:
            badge_lbl = QLabel(badge)
            badge_lbl.setAlignment(Qt.AlignCenter)
            badge_lbl.setStyleSheet(
                "font-size: 9px; font-family: 'JetBrains Mono', monospace; "
                "font-weight: 700; letter-spacing: 2px; padding: 2px 8px; "
                "border-radius: 10px; background: rgba(34,197,94,0.12); "
                "border: 1px solid rgba(34,197,94,0.30); color: #22c55e; "
                "border: none;"
            )
            layout.addWidget(badge_lbl)


class HomePage(QWidget):
    """
    Home screen with 3×2 tile grid.
    Emits navigate(str) with the target screen name.
    """

    navigate = Signal(str)   # e.g. "connect", "live", "scan", "files", "settings"

    # Tile definitions: (icon, label, screen, variant, badge)
    TILES = [
        ("↗",  "Connect",   "connect",  "featured", ""),
        ("🎥", "Live View", "live",     "live",     "LIVE"),
        ("⬡",  "Scan",      "scan",     "default",  ""),
        ("📁", "Files",     "files",    "default",  ""),
        ("≡",  "Settings",  "settings", "default",  ""),
        ("🔬", "About",     "about",    "default",  ""),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)
        outer.setContentsMargins(0, 0, 0, 0)

        grid = QGridLayout()
        grid.setSpacing(16)

        for i, (icon, label, screen, variant, badge) in enumerate(self.TILES):
            tile = TileButton(icon, label, variant, badge)
            tile.clicked.connect(lambda _, s=screen: self.navigate.emit(s))
            row, col = divmod(i, 3)
            grid.addWidget(tile, row, col)

        outer.addLayout(grid)
