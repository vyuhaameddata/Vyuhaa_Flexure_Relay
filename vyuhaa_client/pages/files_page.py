"""
Vyuhaa Remote Client — Files Page
Two-panel: sidebar (search/filter) + main (file grid/list browser).
"""

from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel,
    QPushButton, QSizePolicy, QScrollArea, QLineEdit,
    QComboBox, QGridLayout, QProgressBar
)
from PySide6.QtCore import Qt, Signal
from styles import TEAL, GREEN, RED, AMBER, BORDER, SURFACE, SURFACE2, BG, TEXT_DIM, TEXT_MID, WHITE


# ── Sample data ───────────────────────────────────────────────────────────────

SAMPLE_FILES = [
    {"name": "PAP_20240315_Zone1_40x.ndpi", "type": "wsi",     "size": "2.3 GB", "date": "15 Mar 2024", "tiles": 2048},
    {"name": "PAP_20240315_Zone2_40x.ndpi", "type": "wsi",     "size": "1.8 GB", "date": "15 Mar 2024", "tiles": 1620},
    {"name": "Cap_20240315_001.tiff",        "type": "capture", "size": "18 MB",  "date": "15 Mar 2024", "tiles": None},
    {"name": "Cap_20240315_002.tiff",        "type": "capture", "size": "18 MB",  "date": "15 Mar 2024", "tiles": None},
    {"name": "Rec_20240315_session.mp4",     "type": "video",   "size": "240 MB", "date": "15 Mar 2024", "tiles": None},
    {"name": "PAP_20240312_Full_20x.ndpi",   "type": "wsi",     "size": "3.1 GB", "date": "12 Mar 2024", "tiles": 3200},
    {"name": "Cap_20240312_overview.tiff",   "type": "capture", "size": "22 MB",  "date": "12 Mar 2024", "tiles": None},
]

TYPE_META = {
    "wsi":     {"label": "WSI",     "color": TEAL,  "icon": "⬡"},
    "capture": {"label": "CAPTURE", "color": AMBER, "icon": "📷"},
    "video":   {"label": "VIDEO",   "color": GREEN, "icon": "🎥"},
}


# ── File card (grid view) ─────────────────────────────────────────────────────

class FileCard(QFrame):
    export_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self._name = info["name"]
        meta = TYPE_META.get(info["type"], TYPE_META["capture"])
        self.setFixedSize(200, 170)
        self.setStyleSheet(
            f"QFrame {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:14px; }}"
            f"QFrame:hover {{ border-color: {meta['color']}; }}"
        )
        v = QVBoxLayout(self); v.setContentsMargins(14,12,14,12); v.setSpacing(6)

        # Icon + type badge row
        top = QHBoxLayout(); top.setSpacing(6)
        icon_lbl = QLabel(meta["icon"])
        icon_lbl.setStyleSheet("font-size:22px; background:transparent;")
        badge = QLabel(meta["label"])
        badge.setStyleSheet(
            f"font-size:9px; font-weight:700; letter-spacing:1px; padding:2px 8px;"
            f"border-radius:8px; background:transparent; color:{meta['color']};"
            f"border:1px solid {meta['color']}; font-family:'JetBrains Mono',monospace;"
        )
        top.addWidget(icon_lbl); top.addWidget(badge); top.addStretch()
        v.addLayout(top)

        # File name
        name_lbl = QLabel(info["name"])
        name_lbl.setWordWrap(True)
        name_lbl.setStyleSheet(
            "font-size:11px; font-weight:600; color:#e2e8f0; background:transparent; line-height:1.4;"
        )
        name_lbl.setFixedHeight(40)
        v.addWidget(name_lbl)

        # Meta row
        meta_row = QHBoxLayout(); meta_row.setSpacing(6)
        size_lbl = QLabel(info["size"])
        size_lbl.setStyleSheet(f"font-size:10px; color:{TEXT_DIM}; background:transparent;")
        date_lbl = QLabel(info["date"])
        date_lbl.setStyleSheet(f"font-size:10px; color:{TEXT_DIM}; background:transparent;")
        meta_row.addWidget(size_lbl); meta_row.addStretch(); meta_row.addWidget(date_lbl)
        v.addLayout(meta_row)

        if info.get("tiles"):
            tile_lbl = QLabel(f"{info['tiles']:,} tiles")
            tile_lbl.setStyleSheet(
                f"font-size:9px; font-family:'JetBrains Mono',monospace; "
                f"color:{TEAL}; background:transparent; letter-spacing:1px;"
            )
            v.addWidget(tile_lbl)
        else:
            v.addStretch()

        # Action row
        act = QHBoxLayout(); act.setSpacing(6)
        exp_btn = QPushButton("↓ Export"); exp_btn.setObjectName("BtnSecondary")
        exp_btn.setFixedHeight(28); exp_btn.setCursor(Qt.PointingHandCursor)
        exp_btn.clicked.connect(lambda: self.export_requested.emit(self._name))
        del_btn = QPushButton("✕"); del_btn.setObjectName("BtnDanger")
        del_btn.setFixedSize(28, 28); del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self._name))
        act.addWidget(exp_btn, 1); act.addWidget(del_btn)
        v.addLayout(act)


# ── File row (list view) ──────────────────────────────────────────────────────

class FileRow(QFrame):
    export_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self._name = info["name"]
        meta = TYPE_META.get(info["type"], TYPE_META["capture"])
        self.setFixedHeight(52)
        self.setStyleSheet(
            f"QFrame {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:10px; }}"
            f"QFrame:hover {{ border-color: {meta['color']}; }}"
        )
        h = QHBoxLayout(self); h.setContentsMargins(14,0,14,0); h.setSpacing(12)

        icon_lbl = QLabel(meta["icon"])
        icon_lbl.setStyleSheet("font-size:18px; background:transparent;")

        badge = QLabel(meta["label"])
        badge.setFixedWidth(60)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"font-size:9px; font-weight:700; letter-spacing:1px; padding:2px 6px;"
            f"border-radius:6px; background:transparent; color:{meta['color']};"
            f"border:1px solid {meta['color']}; font-family:'JetBrains Mono',monospace;"
        )

        name_lbl = QLabel(info["name"])
        name_lbl.setStyleSheet("font-size:12px; font-weight:500; color:#e2e8f0; background:transparent;")
        name_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        size_lbl = QLabel(info["size"])
        size_lbl.setStyleSheet(f"font-size:11px; color:{TEXT_DIM}; background:transparent; min-width:60px;")
        date_lbl = QLabel(info["date"])
        date_lbl.setStyleSheet(f"font-size:11px; color:{TEXT_DIM}; background:transparent; min-width:90px;")

        exp_btn = QPushButton("↓"); exp_btn.setObjectName("BtnSecondary")
        exp_btn.setFixedSize(30, 30); exp_btn.setCursor(Qt.PointingHandCursor)
        exp_btn.clicked.connect(lambda: self.export_requested.emit(self._name))
        del_btn = QPushButton("✕"); del_btn.setObjectName("BtnDanger")
        del_btn.setFixedSize(30, 30); del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self._name))

        h.addWidget(icon_lbl); h.addWidget(badge); h.addWidget(name_lbl)
        h.addWidget(size_lbl); h.addWidget(date_lbl)
        h.addWidget(exp_btn);  h.addWidget(del_btn)


# ── Files Page ────────────────────────────────────────────────────────────────

class FilesPage(QWidget):
    export_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._view   = "grid"   # 'grid' | 'list'
        self._filter = "all"    # 'all' | 'wsi' | 'capture' | 'video'
        self._files  = list(SAMPLE_FILES)
        self._filter_btns: dict[str, QPushButton] = {}
        self._view_btns:   dict[str, QPushButton] = {}
        self._build_ui()
        self._load_files()

    def _build_ui(self):
        root = QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────────────────────
        sidebar = QFrame(); sidebar.setObjectName("SideBar"); sidebar.setFixedWidth(280)
        sv = QVBoxLayout(sidebar); sv.setContentsMargins(0,0,0,0); sv.setSpacing(0)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        sw = QWidget(); sv2 = QVBoxLayout(sw); sv2.setContentsMargins(20,24,20,16); sv2.setSpacing(10)

        title = QLabel("Files"); title.setObjectName("SidebarTitle"); sv2.addWidget(title)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{BORDER};max-height:1px;border:none;"); sv2.addWidget(sep)
        sv2.addSpacing(4)

        # Search
        search_lbl = QLabel("SEARCH"); search_lbl.setObjectName("FieldLabel"); sv2.addWidget(search_lbl)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search files…")
        self.search.textChanged.connect(self._load_files); sv2.addWidget(self.search)

        # Filter tabs
        filter_lbl = QLabel("FILTER BY TYPE"); filter_lbl.setObjectName("FieldLabel"); sv2.addWidget(filter_lbl)
        for fid, flbl in (("all","All"),("wsi","WSI"),("capture","Captures"),("video","Videos")):
            b = QPushButton(flbl)
            b.setObjectName("FilterTabActive" if fid=="all" else "FilterTab")
            b.setCursor(Qt.PointingHandCursor); b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _, f=fid, btn=b: self._set_filter(f, btn))
            self._filter_btns[fid] = b; sv2.addWidget(b)

        # Sort
        sort_lbl = QLabel("SORT BY"); sort_lbl.setObjectName("FieldLabel"); sv2.addWidget(sort_lbl)
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Date (newest first)","Name (A–Z)","Size (largest first)"])
        self.sort_combo.currentIndexChanged.connect(self._load_files); sv2.addWidget(self.sort_combo)
        sv2.addSpacing(6)

        # File count
        self.count_lbl = QLabel("7 files")
        self.count_lbl.setStyleSheet(f"font-size:12px; color:{TEXT_DIM}; background:transparent;")
        sv2.addWidget(self.count_lbl)

        # Storage bar
        store_lbl = QLabel("STORAGE USED"); store_lbl.setObjectName("FieldLabel"); sv2.addWidget(store_lbl)
        store_bar = QProgressBar(); store_bar.setRange(0,100); store_bar.setValue(62)
        store_bar.setFixedHeight(5); store_bar.setTextVisible(False); sv2.addWidget(store_bar)
        store_detail = QLabel("124 GB of 200 GB used")
        store_detail.setStyleSheet(f"font-size:10px; color:{TEXT_DIM}; background:transparent;")
        sv2.addWidget(store_detail)
        sv2.addStretch()

        scroll.setWidget(sw); sv.addWidget(scroll)
        root.addWidget(sidebar)

        # ── Main panel ────────────────────────────────────────────────────
        main = QWidget(); main_v = QVBoxLayout(main); main_v.setContentsMargins(0,0,0,0); main_v.setSpacing(0)

        # Toolbar
        tb = QFrame(); tb.setObjectName("FilesToolbar"); tb.setFixedHeight(44)
        tb_h = QHBoxLayout(tb); tb_h.setContentsMargins(16,0,16,0); tb_h.setSpacing(8)
        sel_lbl = QLabel("FILES"); sel_lbl.setStyleSheet(
            f"font-size:11px; font-family:'JetBrains Mono',monospace; font-weight:700; "
            f"color:{TEXT_DIM}; background:transparent; letter-spacing:2px;"
        )
        exp_all = QPushButton("↓ Export Selected"); exp_all.setObjectName("BtnSecondary"); exp_all.setFixedHeight(30)
        exp_all.setCursor(Qt.PointingHandCursor)
        del_all = QPushButton("✕ Delete Selected"); del_all.setObjectName("BtnDanger"); del_all.setFixedHeight(30)
        del_all.setCursor(Qt.PointingHandCursor)

        vsep = QFrame(); vsep.setFrameShape(QFrame.VLine)
        vsep.setStyleSheet(f"color:{BORDER};background:{BORDER};border:none;max-width:1px;")

        for vid, vlbl in (("grid","⊞"),("list","≡")):
            b = QPushButton(vlbl)
            b.setObjectName("ViewBtnActive" if vid=="grid" else "ViewBtn")
            b.setFixedSize(28,28); b.setCursor(Qt.PointingHandCursor); b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _, v=vid, btn=b: self._set_view(v, btn))
            self._view_btns[vid] = b

        tb_h.addWidget(sel_lbl); tb_h.addStretch()
        tb_h.addWidget(exp_all); tb_h.addWidget(del_all); tb_h.addWidget(vsep)
        for b in self._view_btns.values(): tb_h.addWidget(b)
        main_v.addWidget(tb)

        # File area
        self.file_scroll = QScrollArea(); self.file_scroll.setWidgetResizable(True)
        self.file_scroll.setFrameShape(QFrame.NoFrame)
        self.file_content = QWidget()
        self.file_lay = QVBoxLayout(self.file_content); self.file_lay.setContentsMargins(16,16,16,16)
        self.file_scroll.setWidget(self.file_content)
        main_v.addWidget(self.file_scroll, stretch=1)
        root.addWidget(main, stretch=1)

    # ── Logic ─────────────────────────────────────────────────────────────

    def _set_filter(self, fid: str, btn: QPushButton):
        self._filter = fid
        for f, b in self._filter_btns.items():
            b.setObjectName("FilterTabActive" if f==fid else "FilterTab")
            b.style().unpolish(b); b.style().polish(b)
        self._load_files()

    def _set_view(self, vid: str, btn: QPushButton):
        self._view = vid
        for v, b in self._view_btns.items():
            b.setObjectName("ViewBtnActive" if v==vid else "ViewBtn")
            b.style().unpolish(b); b.style().polish(b)
        self._load_files()

    def _load_files(self):
        # Clear
        while self.file_lay.count():
            item = self.file_lay.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        query = self.search.text().lower()
        files = [f for f in self._files
                 if (self._filter == "all" or f["type"] == self._filter)
                 and (not query or query in f["name"].lower())]

        self.count_lbl.setText(f"{len(files)} file{'s' if len(files)!=1 else ''}")

        if self._view == "grid":
            grid = QGridLayout(); grid.setSpacing(12)
            for i, info in enumerate(files):
                card = FileCard(info)
                card.export_requested.connect(self.export_requested)
                card.delete_requested.connect(self.delete_requested)
                grid.addWidget(card, i//3, i%3)
            wrapper = QWidget(); wrapper.setLayout(grid)
            self.file_lay.addWidget(wrapper)
        else:
            for info in files:
                row = FileRow(info)
                row.export_requested.connect(self.export_requested)
                row.delete_requested.connect(self.delete_requested)
                self.file_lay.addWidget(row)

        self.file_lay.addStretch()
