# -*- coding: utf-8 -*-
"""主窗口：三栏布局 + 完整主流程接线

布局（沿用 v4 的三段式视觉语言）
--------------------------------
  ┌ 自绘标题栏 ─────────────────────────────────────────────┐
  │  Hero 区：产品名 + 副标题 + 大搜索框                    │
  ├ 筛选栏 ┬ 结果列表（虚拟化） ┬ 详情面板（4 个预建分区）─┤
  └ 状态栏：搜索状态 / 数据版本 / 免责声明（100ms 节流）───┘

依赖注入
--------
``MainWindow(index=..., repo=..., features=...)`` 三个参数都可省略；
省略时自动加载内置数据与用户库。测试里直接注入临时依赖，无需碰真实用户目录。
"""

import os
import sqlite3
from typing import Any, Dict, List, Optional

from PySide2.QtCore import QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide2.QtGui import (
    QIcon,
    QColor,
    QCursor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide2.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QLabel,
    QListView,
    QMainWindow,
    QShortcut,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import resources
from ..datasource import migrate
from ..repo import UserRepository, user_db_path
from ..repo.lock import SingleInstanceLock
from ..repo import lock_path
from ..search import SearchIndex
from .detail import DetailPane
from .features import AppFeatures
from .results import CodeModel, ResultDelegate
from .settings_dialog import SettingsDialog
from .theme import get_theme, scrollbar_qss
from .widgets import (
    EmptyState,
    FilterColumn,
    SearchBox,
    StatusBar,
    TitleBar,
    Toast,
    set_font_scale,
    ui_font,
)

DEBOUNCE_MS = 300
CLOCK_MS = 16
MIN_WIDTH = 900
MIN_HEIGHT = 560

# ---------------------------------------------------------------------
# 外部配置的内置默认值（config/*.json 缺失或损坏时用这些）
# ---------------------------------------------------------------------
DEFAULT_APP_CONFIG = {
    "theme": "dark",
    "font_size": 10,
    "window": {"width": 1200, "height": 800, "min_width": 900, "min_height": 560},
    "disclaimer": "仅供参考，不替代官方支持",
}

DEFAULT_SEARCH_CONFIG = {
    "debounce_ms": DEBOUNCE_MS,
    "max_results": 200,
    "fuzzy_fallback": True,
}

DEFAULT_SHORTCUTS = {
    "focus_search": "Ctrl+K",
    "copy": "Ctrl+C",
    "favorite": "Ctrl+D",
    "settings": "Ctrl+,",
    "filter_all": "Ctrl+1",
    "filter_favorite": "Ctrl+2",
    "filter_recent": "Ctrl+3",
    "escape": "Escape",
}


def project_root():
    # type: () -> str
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def default_db_path():
    # type: () -> str
    return resources.runtime_db_path()


def records_from_db(db_path):
    # type: (Optional[str]) -> Optional[List[Dict[str, Any]]]
    """从内置 SQLite 库读记录；库不存在或损坏返回 None。"""
    path = db_path or default_db_path()
    if not os.path.exists(path):
        return None
    connection = None
    try:
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM stop_codes").fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def default_records():
    # type: () -> List[Dict[str, Any]]
    """加载内置数据：优先 SQLite（更新包生效），回退到 JSON。"""
    resources.ensure_runtime_db()
    from_db = records_from_db(default_db_path())
    if from_db:
        return from_db

    json_path = os.path.join(project_root(), "bluescreen_data.json")
    if not os.path.exists(json_path):
        return []
    try:
        return list(migrate.iter_records(migrate.load_json(json_path)))
    except Exception:
        return []


class MainWindow(QMainWindow):
    """主窗口。所有交互在此编排，控件本身不碰数据层。"""

    def __init__(self, index=None, repo=None, features=None, parent=None):
        # type: (Optional[SearchIndex], Optional[UserRepository], Optional[AppFeatures], object) -> None
        super().__init__(parent)

        self.features = features or AppFeatures()

        # ---- 外部配置（config/*.json）：缺失/损坏都静默回退默认值 ----
        self.app_config = resources.load_config("app", DEFAULT_APP_CONFIG)
        self.search_config = resources.load_config("search", DEFAULT_SEARCH_CONFIG)
        self.shortcut_config = resources.load_config("shortcuts", DEFAULT_SHORTCUTS)
        self.disclaimer = resources.as_text(
            self.app_config.get("disclaimer"), DEFAULT_APP_CONFIG["disclaimer"]
        )
        window_cfg = self.app_config.get("window")
        self.window_width = resources.as_nested_int(window_cfg, "width", 1200, 700, 6000)
        self.window_height = resources.as_nested_int(window_cfg, "height", 800, 480, 4000)
        self.min_width = resources.as_nested_int(window_cfg, "min_width", MIN_WIDTH, 640, 4000)
        self.min_height = resources.as_nested_int(window_cfg, "min_height", MIN_HEIGHT, 400, 3000)

        self._owns_repo = repo is None
        self._lock = None  # type: Optional[SingleInstanceLock]

        if index is None:
            index = SearchIndex(
                default_records(),
                max_results=resources.as_int(
                    self.search_config.get("max_results"), 200, 1, 5000
                ),
                fuzzy_enabled=resources.as_bool(
                    self.search_config.get("fuzzy_fallback"), True
                ),
            )
        self.index = index

        if repo is None:
            self._lock = SingleInstanceLock(lock_path())
            self._lock.acquire()
            repo = UserRepository(user_db_path())
        self.repo = repo

        self.theme_key = "dark"
        self.theme = get_theme("dark")
        self._current_row = -1
        self._pending = None
        self._closing = False
        self._settings_dialog = None

        # 字号必须在建控件之前生效，否则控件会按旧字号构造
        self.font_size = self._read_font_size()
        set_font_scale(self.font_size / 10.0)

        self.setWindowTitle("蓝屏代码查询器 2.0")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumSize(self.min_width, self.min_height)
        self.resize(self.window_width, self.window_height)
        self._apply_window_icon()

        self._build_ui()
        self._apply_settings()
        self._build_shortcuts()
        self._restore_geometry()

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(
            resources.as_int(self.search_config.get("debounce_ms"), DEBOUNCE_MS, 0, 5000)
        )
        self._debounce.timeout.connect(self.run_search)

        self._clock = QTimer(self)
        self._clock.setInterval(CLOCK_MS)
        self._clock.timeout.connect(self._tick)
        if self.features.animations:
            self._clock.start()

        self.refresh_counts()
        self.refresh()

    def _apply_window_icon(self):
        # type: () -> None
        path = resources.find_asset(os.path.join("assets", "BlueScreenQuery.ico"))
        if not path:
            return
        try:
            icon = QIcon(path)
            if icon.isNull():
                return
            self.setWindowIcon(icon)
            QApplication.setWindowIcon(icon)
        except Exception:
            pass

    # ================================================================ 构建
    def _build_ui(self):
        # type: () -> None
        central = QWidget(self)
        central.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)

        self.title_bar = TitleBar(
            self.theme,
            self.features,
            handlers={
                "settings": self.open_settings,
                "theme": self.toggle_theme,
                "min": self.showMinimized,
                "max": self._toggle_maximized,
                "close": self.close,
            },
            parent=central,
        )
        outer.addWidget(self.title_bar)

        # ---------------- Hero ----------------
        hero = QWidget(central)
        hero.setAttribute(Qt.WA_TranslucentBackground, True)
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(26, 12, 26, 16)
        hero_layout.setSpacing(10)

        title = QLabel("蓝屏代码查询器", hero)
        title.setFont(ui_font(21, bold=True))
        title.setObjectName("heroTitle")
        hero_layout.addWidget(title)

        subtitle = QLabel("停止代码 · 英文名 · 中文症状，三路皆可查", hero)
        subtitle.setFont(ui_font(9))
        subtitle.setObjectName("heroSubtitle")
        hero_layout.addWidget(subtitle)

        self.search_box = SearchBox(self.theme, self.features, hero)
        self.search_box.setPlaceholderText("输入 0x0000007B、7b、INACCESSIBLE_BOOT_DEVICE 或中文症状…")
        self.search_box.textChanged.connect(self._on_text_changed)
        self.search_box.returnPressed.connect(self._on_return)
        hero_layout.addWidget(self.search_box)

        outer.addWidget(hero)

        # ---------------- 三栏 ----------------
        body = QSplitter(Qt.Horizontal, central)
        body.setChildrenCollapsible(False)
        body.setHandleWidth(8)

        self.filter_column = FilterColumn(self.theme, self.features, body)
        self.filter_column.changed.connect(self._on_mode_changed)
        body.addWidget(self.filter_column)

        middle = QWidget(body)
        middle.setAttribute(Qt.WA_TranslucentBackground, True)
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(8)

        self.count_label = QLabel("", middle)
        self.count_label.setFont(ui_font(9))
        self.count_label.setContentsMargins(6, 0, 6, 0)
        middle_layout.addWidget(self.count_label)

        self.model = CodeModel(self)
        self.result_view = QListView(middle)
        self.result_view.setModel(self.model)
        self.result_view.setUniformItemSizes(True)
        self.result_view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.result_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.result_view.setSelectionMode(QAbstractItemView.NoSelection)
        self.result_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.result_view.setFrameShape(QListView.NoFrame)
        self.result_view.setMouseTracking(True)
        self.result_view.setFocusPolicy(Qt.StrongFocus)
        self.result_view.setSpacing(0)

        self.delegate = ResultDelegate(self.theme, self.result_view, self.features, middle)
        self.result_view.setItemDelegate(self.delegate)
        self.result_view.clicked.connect(self._on_row_clicked)
        self.result_view.setMouseTracking(True)
        middle_layout.addWidget(self.result_view, 1)

        self.empty_state = EmptyState(self.theme, middle)
        middle_layout.addWidget(self.empty_state, 1)
        self.empty_state.setVisible(False)

        body.addWidget(middle)

        self.detail = DetailPane(self.theme, self.features, on_copy=self._copy_text, parent=body)
        self.detail.favorite_requested.connect(self.toggle_favorite)
        self.detail.copy_requested.connect(self.copy_current)
        body.addWidget(self.detail)

        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 5)
        body.setStretchFactor(2, 6)
        body.setSizes([190, 470, 520])
        self.body_splitter = body
        outer.addWidget(body, 1)

        # ---------------- 状态栏 ----------------
        self.status_bar = StatusBar(self.theme, central)
        outer.addWidget(self.status_bar)

        # ---------------- Toast ----------------
        self.toast = Toast(self.features, self.theme, central)

    # ================================================================ 主题
    def _apply_settings(self):
        # type: () -> None
        stored = None
        try:
            stored = self.repo.get_setting("theme")
        except Exception:
            stored = None
        if stored in ("dark", "light"):
            self.theme_key = stored
        else:
            self.theme_key = resources.as_theme(self.app_config.get("theme"), "dark")
        self.apply_theme(self.theme_key)

    def apply_theme(self, key):
        # type: (str) -> None
        self.theme_key = key if key in ("dark", "light") else "dark"
        self.theme = get_theme(self.theme_key)
        theme = self.theme

        self.title_bar.apply_theme(theme)
        self.search_box.apply_theme(theme)
        self.filter_column.apply_theme(theme)
        self.delegate.apply_theme(theme)
        self.detail.apply_theme(theme)
        self.empty_state.theme = theme
        self.empty_state.update()
        self.status_bar.apply_theme(theme)
        self.toast.apply_theme(theme)

        self.result_view.setStyleSheet(
            "QListView{background:transparent;border:none;}" + scrollbar_qss(theme)
        )
        self.count_label.setStyleSheet(
            "color:%s;background:transparent;border:none;" % theme["faint"]
        )
        for name, color_key in (
            ("heroTitle", "text"),
            ("heroSubtitle", "faint"),
        ):
            widget = self.findChild(QLabel, name)
            if widget is not None:
                widget.setStyleSheet(
                    "color:%s;background:transparent;border:none;" % theme[color_key]
                )
        self.update()

    def toggle_theme(self):
        # type: () -> None
        new_key = "light" if self.theme_key == "dark" else "dark"
        self.apply_theme(new_key)
        try:
            self.repo.set_setting("theme", new_key)
        except Exception:
            pass
        self.show_toast("主题：%s" % ("深色" if new_key == "dark" else "浅色"))

    # ================================================================ 窗口
    def _toggle_maximized(self):
        # type: () -> None
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def paintEvent(self, event):
        theme = self.theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect().adjusted(6, 6, -6, -6)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 20, 20)
        painter.setClipPath(path)

        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor(theme["bg"][0]))
        gradient.setColorAt(0.55, QColor(theme["bg"][1]))
        gradient.setColorAt(1.0, QColor(theme["bg"][2]))
        painter.fillPath(path, gradient)

        # 静态光晕（不做逐帧动画，避免无谓的重绘开销）
        for cx, cy, radius, alpha in (
            (rect.left() + rect.width() * 0.18, rect.top() + rect.height() * 0.10, rect.width() * 0.42, 0.13),
            (rect.left() + rect.width() * 0.85, rect.top() + rect.height() * 0.75, rect.width() * 0.38, 0.10),
        ):
            glow = QRadialGradient(QPointF(cx, cy), radius)
            glow.setColorAt(0.0, QColor(theme["accent"]).lighter(120))
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(QPointF(cx, cy), radius, radius)

        painter.setClipping(False)
        painter.setPen(QPen(QColor(theme["border"]), 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    # ================================================================ 快捷键
    def _shortcut_sequence(self, key):
        # type: (str) -> str
        """取配置里的键序列；空串/非法都视为「禁用这一条」。"""
        raw = self.shortcut_config.get(key, DEFAULT_SHORTCUTS.get(key, ""))
        if not isinstance(raw, str):
            return DEFAULT_SHORTCUTS.get(key, "")
        text = raw.strip()
        if not text or text.lower() in ("none", "disabled", "off"):
            return ""
        return text

    def _build_shortcuts(self):
        # type: () -> None
        self._shortcuts = []  # type: list

        def bind(key, handler, widget=None, context=None):
            sequence = self._shortcut_sequence(key)
            if not sequence:
                return None
            try:
                shortcut = QShortcut(sequence, widget or self)
            except Exception:
                # 用户写了非法的键序列：只跳过这一条，不影响其它快捷键
                return None
            if context is not None:
                shortcut.setContext(context)
            shortcut.activated.connect(handler)
            self._shortcuts.append(shortcut)
            return shortcut

        bind("focus_search", self.focus_search)
        bind("copy", self.copy_current)
        bind("favorite", self.toggle_favorite)
        bind("settings", self.open_settings)
        bind("filter_all", lambda: self.filter_column.set_mode("all"))
        bind("filter_favorite", lambda: self.filter_column.set_mode("favorite"))
        bind("filter_recent", lambda: self.filter_column.set_mode("recent"))
        bind("escape", self._on_escape)

        # 列表内方向键固定绑定（不开放配置，避免与输入框抢键）
        widget_context = Qt.WidgetWithChildrenShortcut
        for sequence, handler in (
            ("Up", lambda: self.move_selection(-1)),
            ("Down", lambda: self.move_selection(1)),
            ("PageUp", lambda: self.move_selection(-8)),
            ("PageDown", lambda: self.move_selection(8)),
            ("Home", lambda: self.select_row(0, True)),
            ("End", lambda: self.select_row(self.model.rowCount() - 1, True)),
            ("Return", self.run_search),
        ):
            shortcut = QShortcut(sequence, self.result_view)
            shortcut.setContext(widget_context)
            shortcut.activated.connect(handler)
            self._shortcuts.append(shortcut)

    def focus_search(self):
        # type: () -> None
        self.search_box.setFocus()
        self.search_box.selectAll()

    def _on_escape(self):
        # type: () -> None
        if self.search_box.text():
            self.search_box.clear()
        else:
            self.detail.set_data(None)

    # ================================================================ 搜索
    def _on_text_changed(self, text):
        # type: (str) -> None
        stripped = (text or "").strip()
        if not stripped:
            self._debounce.stop()
            self.refresh()
            return
        if len(stripped) <= 1:
            self._debounce.stop()
            self.run_search()
            return
        self._set_status("输入中…")
        if self.features.animations:
            self._debounce.start()
        else:
            self._debounce.stop()
            self.run_search()

    def _on_return(self):
        # type: () -> None
        self._debounce.stop()
        self.run_search()

    def _on_mode_changed(self, mode):
        # type: (str) -> None
        self.refresh()

    def _records_for_mode(self, mode):
        # type: (str) -> List[Dict[str, Any]]
        records = self.index.records
        if mode == "favorite":
            codes = set(self._safe_favorites())
            return [item for item in records if str(item.get("stop_code")) in codes]
        if mode == "recent":
            codes = set(self._safe_recent_codes())
            return [item for item in records if str(item.get("stop_code")) in codes]
        return records

    def _safe_favorites(self):
        # type: () -> List[str]
        try:
            return self.repo.favorite_codes()
        except Exception:
            return []

    def _safe_recent_codes(self):
        # type: () -> List[str]
        try:
            rows = self.repo.list_history(self.repo.history_limit)
        except Exception:
            return []
        return [str(row.get("stop_code")) for row in rows if row.get("stop_code")]

    def run_search(self):
        # type: () -> None
        """同步执行一次搜索；UI 状态、详情、历史一次到位。"""
        query = self.search_box.text().strip()
        mode = self.filter_column.mode
        self._set_status("搜索中…")
        self.empty_state.setVisible(False)

        if query:
            result = self.index.search(query)
            items = result.items
            scores = result.scores
            if mode in ("favorite", "recent"):
                allowed = set(
                    self._safe_favorites()
                    if mode == "favorite"
                    else self._safe_recent_codes()
                )
                pairs = [
                    (score, item)
                    for score, item in zip(scores, items)
                    if str(item.get("stop_code")) in allowed
                ]
                items = [item for _, item in pairs]
                scores = [score for score, _ in pairs]
        else:
            items = self._records_for_mode(mode)
            scores = [None] * len(items)

        self._debounce.stop()
        self.model.set_list(items, scores)
        self.delegate.keyword = query
        self.delegate.favorites = set(self._safe_favorites())
        self.delegate.intro = 0.0 if self.features.animations else 1.0
        self._current_row = -1

        if items:
            self.result_view.setVisible(True)
            self.empty_state.setVisible(False)
            self._set_status(
                "匹配 %d 条 · %s" % (len(items), query) if query else "共 %d 条" % len(items)
            )
            self.select_row(0, True)
        else:
            self.result_view.setVisible(False)
            self.empty_state.setVisible(True)
            if query:
                self.empty_state.set_state(
                    "noresult",
                    "没有匹配结果",
                    "试试更短的代码片段，或改用英文名 / 中文症状",
                )
                self._set_status("未找到匹配：%s" % query)
            else:
                self.empty_state.set_state(
                    "empty",
                    "当前筛选下暂无记录",
                    "切换左侧筛选，或在上方输入要查询的蓝屏代码",
                )
                self._set_status("0 条")
            self.detail.set_data(None)

        self.count_label.setText(
            ("匹配 %d 条" % len(items)) if query else ("共 %d 条" % len(items))
        )
        self.refresh_counts()

        # 自动记录非空查询（去重由用户库负责）
        if query:
            top = items[0] if items else None
            try:
                self.repo.add_history(
                    query,
                    stop_code=(top.get("stop_code") if top else None),
                )
                self.refresh_counts()
            except Exception:
                pass

        self.result_view.viewport().update()

    def refresh(self):
        # type: () -> None
        self.run_search()

    def refresh_counts(self):
        # type: () -> None
        try:
            favorites = self.repo.favorite_count()
        except Exception:
            favorites = 0
        try:
            recent = self.repo.history_count()
        except Exception:
            recent = 0
        self.filter_column.set_counts(len(self.index), favorites, recent)

    # ================================================================ 选择
    def select_row(self, row, open_detail=False):
        # type: (int, bool) -> None
        count = self.model.rowCount()
        if count == 0:
            return
        row = max(0, min(count - 1, int(row)))

        if self.features.animations:
            if self.delegate.selected_to < 0:
                self.delegate.selected_from = row
                self.delegate.selected_t = 1.0
            else:
                self.delegate.selected_from = self.delegate.selected_to
                self.delegate.selected_t = 0.0
            self.delegate.selected_to = row
        else:
            self.delegate.selected_from = row
            self.delegate.selected_to = row
            self.delegate.selected_t = 1.0

        self._current_row = row
        self.result_view.setCurrentIndex(self.model.index(row, 0))
        self.result_view.scrollTo(self.model.index(row, 0))

        if open_detail or True:
            self._pending = self.model.item_at(row)
            if self.features.animations:
                QTimer.singleShot(60, self._flush_detail)
            else:
                self._flush_detail()

    def _flush_detail(self):
        # type: () -> None
        item = self._pending
        self._pending = None
        if item is None:
            return
        code = str(item.get("stop_code") or "")
        is_favorite = False
        try:
            is_favorite = self.repo.is_favorite(code)
        except Exception:
            is_favorite = False
        self.detail.set_data(item, keyword=self.search_box.text().strip(), is_favorite=is_favorite)

    def move_selection(self, delta):
        # type: (int) -> None
        if self.model.rowCount() == 0:
            return
        target = self._current_row + int(delta)
        self.select_row(target, True)

    def _on_row_clicked(self, index):
        # type: (object) -> None
        if index is not None and index.isValid():
            self.select_row(index.row(), True)

    # ================================================================ 复制
    def _clipboard(self):
        # type: () -> Optional[object]
        try:
            return QApplication.clipboard()
        except Exception:
            return None

    def _copy_text(self, title, text):
        # type: (str, str) -> None
        payload = (text or "").strip()
        if not payload:
            self.show_toast("「%s」暂无信息可复制" % title)
            return
        clipboard = self._clipboard()
        if clipboard is None:
            self.show_toast("剪贴板不可用，请手动选择复制")
            return
        try:
            clipboard.setText(payload)
        except Exception:
            self.show_toast("复制失败，请手动选择复制")
            return
        if clipboard.text() != payload:
            self.show_toast("复制未成功，请手动选择复制")
            return
        self.show_toast("已复制%s" % (("「%s」" % title) if title else ""))

    def copy_current(self):
        # type: () -> None
        """复制当前详情整条；若焦点在输入框且有选中文本，让原生复制生效。"""
        if self._input_has_selection():
            return
        payload = self.detail.plain_text_for_copy()
        if not payload:
            self.show_toast("请先选择一条记录")
            return
        self._copy_text("", payload)

    def _input_has_selection(self):
        # type: () -> bool
        try:
            widget = QApplication.focusWidget()
        except Exception:
            return False
        return bool(widget is self.search_box and self.search_box.hasSelectedText())

    def toggle_favorite(self):
        # type: () -> None
        record = self.detail.current
        if not record:
            self.show_toast("请先选择一条记录")
            return
        code = str(record.get("stop_code") or "")
        try:
            now_favorite = self.repo.toggle_favorite(code)
        except Exception:
            self.show_toast("收藏失败，请检查用户数据目录权限")
            return
        self.detail.set_favorite(now_favorite)
        self.delegate.favorites = set(self._safe_favorites())
        self.result_view.viewport().update()
        self.refresh_counts()
        self.show_toast("已收藏 %s" % code if now_favorite else "已取消收藏 %s" % code)

    # ================================================================ 反馈
    def show_toast(self, text):
        # type: (str) -> None
        self.toast.show_message(text)

    def _set_status(self, left):
        # type: (str) -> None
        version = "数据版本 v%s · 内置 %d 条" % (
            self.data_version(),
            len(self.index),
        )
        self.status_bar.set_texts(left=left, middle=version, right=self.disclaimer)

    # ================================================================ 心跳
    def _tick(self):
        # type: () -> None
        if not self.features.animations:
            return
        delegate = self.delegate
        changed = False

        if delegate.intro < 1.0:
            delegate.intro = min(1.0, delegate.intro + 0.020)
            changed = True
        if delegate.selected_t < 1.0:
            delegate.selected_t = min(1.0, delegate.selected_t + 0.075)
            changed = True
        target_hover = 1.0 if delegate.hover_row >= 0 else 0.0
        if abs(delegate.hover_t - target_hover) > 0.001:
            step = 0.11
            if delegate.hover_t < target_hover:
                delegate.hover_t = min(target_hover, delegate.hover_t + step)
            else:
                delegate.hover_t = max(target_hover, delegate.hover_t - step)
            changed = True

        if changed:
            self.result_view.viewport().update()

    # ================================================================ 设置
    def _read_font_size(self):
        # type: () -> int
        try:
            stored = self.repo.get_setting("font_size")
        except Exception:
            stored = None
        if isinstance(stored, int) and 8 <= stored <= 16:
            return stored
        return resources.as_int(self.app_config.get("font_size"), 10, 8, 16)

    def _restore_geometry(self):
        # type: () -> None
        try:
            geometry = self.repo.get_setting("window_geometry")
        except Exception:
            geometry = None
        if not isinstance(geometry, (list, tuple)) or len(geometry) != 4:
            return
        try:
            x, y, width, height = [int(value) for value in geometry]
        except (TypeError, ValueError):
            return
        if width >= self.min_width and height >= self.min_height:
            self.setGeometry(x, y, width, height)

    def _save_geometry(self):
        # type: () -> None
        try:
            geometry = self.geometry()
            self.repo.set_setting(
                "window_geometry",
                [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
            )
        except Exception:
            pass

    def _apply_font_scale(self):
        # type: () -> None
        set_font_scale(self.font_size / 10.0)
        self.delegate.apply_theme(self.theme)
        self.detail.apply_theme(self.theme)
        self.result_view.viewport().update()
        self.update()

    def data_version(self):
        # type: () -> str
        """数据版本：优先读内置库 meta，回退到 schema 版本常量。"""
        path = default_db_path()
        if os.path.exists(path):
            connection = None
            try:
                connection = sqlite3.connect(path)
                row = connection.execute(
                    "SELECT value FROM meta WHERE key = 'data_version'"
                ).fetchone()
                if row and row[0]:
                    return str(row[0])
            except Exception:
                pass
            finally:
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        pass
        return migrate.SCHEMA_VERSION

    def reload_data(self):
        # type: () -> None
        """重新加载内置数据（离线更新包应用后调用）。"""
        self.index = SearchIndex(default_records())
        self.refresh_counts()
        self.run_search()

    def open_settings(self):
        # type: () -> None
        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(
                self.repo,
                self.features,
                theme_key=self.theme_key,
                font_size=self.font_size,
                data_version=self.data_version(),
                record_count=len(self.index),
                db_path=default_db_path(),
                parent=self,
            )
            self._settings_dialog.changed.connect(self._on_settings_changed)
            self._settings_dialog.finished.connect(self._on_settings_closed)
        self._settings_dialog.refresh_info()
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def _on_settings_changed(self):
        # type: () -> None
        dialog = self._settings_dialog
        if dialog is None:
            return
        if dialog.font_size != self.font_size:
            self.font_size = dialog.font_size
            try:
                self.repo.set_setting("font_size", self.font_size)
            except Exception:
                pass
            self._apply_font_scale()
        if dialog.theme_key != self.theme_key:
            self.apply_theme(dialog.theme_key)
        self.refresh_counts()

    def _on_settings_closed(self, _result=None):
        # type: (object) -> None
        self._settings_dialog = None
        self.reload_data()

    # ================================================================ 关闭
    def closeEvent(self, event):
        # type: (object) -> None
        self._closing = True
        self._save_geometry()
        try:
            self._debounce.stop()
            self._clock.stop()
        except Exception:
            pass
        try:
            self.status_bar.flush_now()
        except Exception:
            pass
        try:
            self.repo.backup()
        except Exception:
            pass
        if self._owns_repo:
            try:
                self.repo.close()
            except Exception:
                pass
        if self._lock is not None:
            self._lock.release()
        super().closeEvent(event)


def create_app(argv=None):
    # type: (Optional[list]) -> tuple
    """创建 QApplication + 主窗口，便于 main.py 与测试复用。"""
    app = QApplication.instance() or QApplication(argv or [])
    app.setApplicationName("BlueScreenQuery")
    window = MainWindow()
    return app, window
