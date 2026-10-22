# -*- coding: utf-8 -*-
"""详情面板：4 个预建分区，切换条目只改文本与可见性（零 widget 重建）

继承 v4 的核心做法：
  分区对象在构造时一次性建好，之后 ``set_data`` 只调用 ``set_text``；
  绝不 ``deleteLater`` + ``new``，因此点击列表任意条目都是瞬时渲染。

2.0 的变化：
  分区字段来自数据层的无损拆分结果——
     含义     <- description（定义）
     通俗解释 <- humor_desc（比喻段）
     技术分析 <- pro_desc（技术段）
     排查步骤 <- solutions（已拆成步骤列表）
  字段缺失一律显示「暂无信息」，不隐藏、不编造（B2=A）。
"""

import html
import json
from typing import Any, Dict, List, Optional

from PySide2.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide2.QtGui import QCursor, QFont, QPainter, QPen
from PySide2.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .theme import SECTION_FIELDS, SECTION_ORDER, mix, qc, scrollbar_qss
from .widgets import body_font_px, code_font, rounded, ui_font

EMPTY_TEXT = "暂无信息"


def _escape(text):
    # type: (Any) -> str
    return html.escape("" if text is None else str(text), quote=False)


def _highlight_html(text, keyword, theme):
    # type: (str, str, dict) -> str
    """把关键词包成高亮 span；文本先转义，避免把数据当 HTML 解释。"""
    escaped = _escape(text)
    needle = (keyword or "").strip()
    if not needle:
        return escaped

    lowered = escaped.lower()
    target = _escape(needle).lower()
    if not target:
        return escaped

    parts = []  # type: List[str]
    cursor = 0
    while True:
        found = lowered.find(target, cursor)
        if found < 0:
            parts.append(escaped[cursor:])
            break
        parts.append(escaped[cursor:found])
        parts.append(
            "<span style='background:%s;color:%s;border-radius:3px;"
            "padding:0 2px;'>%s</span>"
            % (theme["mark_bg"], theme["mark_fg"], escaped[found : found + len(target)])
        )
        cursor = found + len(target)
    return "".join(parts)


def _steps_from(value):
    # type: (Any) -> List[str]
    """把 solutions 字段还原成步骤列表；兼容 JSON 字符串 / 列表 / 纯文本。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
    return [text]


class Section(QFrame):
    """单个分区卡片：标题 + 彩色圆点 + 复制本段 + 折叠。"""

    def __init__(self, title, theme, features, on_copy=None, parent=None):
        # type: (str, dict, object, object, object) -> None
        super().__init__(parent)
        self.title = title
        self.theme = theme
        self.features = features
        self.on_copy = on_copy
        self._collapsed = False
        self._plain_text = ""
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.dot = QWidget(self)
        self.dot.setFixedSize(10, 10)
        head.addWidget(self.dot)

        self.title_label = QLabel(title, self)
        self.title_label.setFont(ui_font(10, bold=True))
        head.addWidget(self.title_label)
        head.addStretch(1)

        self.copy_button = QToolButton(self)
        self.copy_button.setText("⧉")
        self.copy_button.setToolTip("复制本段")
        self.copy_button.setFixedSize(24, 24)
        self.copy_button.setCursor(QCursor(Qt.PointingHandCursor))
        self.copy_button.clicked.connect(self._copy)
        head.addWidget(self.copy_button)

        self.toggle_button = QToolButton(self)
        self.toggle_button.setFixedSize(24, 24)
        self.toggle_button.setArrowType(Qt.UpArrow)
        self.toggle_button.setCursor(QCursor(Qt.PointingHandCursor))
        self.toggle_button.clicked.connect(self.toggle)
        head.addWidget(self.toggle_button)

        layout.addLayout(head)

        self.body = QLabel(self)
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        layout.addWidget(self.body)

    # ---------------------------------------------------------- 内容
    def set_content(self, value, keyword="", as_steps=False):
        # type: (Any, str, bool) -> None
        theme = self.theme

        if as_steps:
            steps = _steps_from(value)
            if steps:
                self._plain_text = "\n".join(
                    "%d. %s" % (index + 1, step.strip())
                    for index, step in enumerate(steps)
                )
                body = "<br/>".join(
                    "%s&nbsp;&nbsp;%s"
                    % (
                        "<span style='color:%s;'>%d.</span>"
                        % (theme["accent"], index + 1),
                        _highlight_html(step.strip(), keyword, theme),
                    )
                    for index, step in enumerate(steps)
                )
            else:
                self._plain_text = EMPTY_TEXT
                body = self._empty_html()
        else:
            text = "" if value is None else str(value).strip()
            if text:
                self._plain_text = text
                body = _highlight_html(text, keyword, theme).replace("\n", "<br/>")
            else:
                self._plain_text = EMPTY_TEXT
                body = self._empty_html()

        self.body.setText(
            "<div style='color:%s;font-size:%dpx;line-height:1.85;'>%s</div>"
            % (theme["text"], body_font_px(), body)
        )

    def _empty_html(self):
        # type: () -> str
        return "<span style='color:%s;'>%s</span>" % (
            self.theme["faint"],
            EMPTY_TEXT,
        )

    def plain_text(self):
        # type: () -> str
        """当前分区的纯文本（供复制用，不含样式）。"""
        return self._plain_text

    def _copy(self):
        if self.on_copy is not None:
            self.on_copy(self.title, self._plain_text)

    # ---------------------------------------------------------- 折叠
    def toggle(self):
        self._collapsed = not self._collapsed
        self.body.setVisible(not self._collapsed)
        self.toggle_button.setArrowType(
            Qt.DownArrow if self._collapsed else Qt.UpArrow
        )

    @property
    def collapsed(self):
        # type: () -> bool
        return self._collapsed

    # ---------------------------------------------------------- 主题
    def apply_theme(self, theme):
        self.theme = theme
        color = theme["sec"].get(self.title, theme["accent"])
        self.dot.setStyleSheet(
            "background:%s;border:none;border-radius:5px;" % color
        )
        self.title_label.setStyleSheet(
            "color:%s;background:transparent;border:none;" % color
        )
        self.body.setStyleSheet("background:transparent;border:none;")
        for button in (self.copy_button, self.toggle_button):
            button.setStyleSheet(
                "QToolButton{background:transparent;border:none;color:%s;"
                "font-size:12px;}"
                "QToolButton:hover{background:%s;border-radius:12px;}"
                % (theme["dim"], theme["chip"])
            )
        self.update()

    def paintEvent(self, event):
        theme = self.theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(qc(theme["border"]), 1.0))
        painter.setBrush(qc(theme["glass"]))
        painter.drawPath(rounded(rect, 14))


class EmptyHint(QWidget):
    """详情区未选中任何条目时的提示。"""

    def __init__(self, theme, parent=None):
        # type: (dict, object) -> None
        super().__init__(parent)
        self.theme = theme
        self.setMinimumHeight(240)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def apply_theme(self, theme):
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        theme = self.theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        center_x = self.width() / 2.0
        center_y = self.height() / 2.0 - 20

        for index in range(3):
            painter.setPen(QPen(qc(theme["accent"], 0.20 - index * 0.05), 1.4))
            painter.setBrush(Qt.NoBrush)
            radius = 28 + index * 15
            painter.drawEllipse(QPointF(center_x, center_y), radius, radius)

        painter.setPen(QPen(qc(theme["accent"], 0.85), 2.0))
        painter.drawEllipse(QPointF(center_x, center_y), 18, 18)
        painter.drawLine(
            QPointF(center_x + 12, center_y + 12),
            QPointF(center_x + 26, center_y + 26),
        )

        painter.setPen(QPen(qc(theme["dim"])))
        painter.setFont(ui_font(10))
        painter.drawText(
            QRect(0, int(center_y + 56), self.width(), 24),
            Qt.AlignCenter,
            "从左侧选择一条查看详细信息",
        )


class DetailPane(QFrame):
    """右侧详情：头部 + 4 个预建分区，全部一次性建好。"""

    favorite_requested = Signal()
    copy_requested = Signal()

    def __init__(self, theme, features, on_copy=None, parent=None):
        # type: (dict, object, object, object) -> None
        super().__init__(parent)
        self.theme = theme
        self.features = features
        self.on_copy = on_copy
        self.current = None  # type: Optional[Dict[str, Any]]
        self.keyword = ""
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("background:transparent;border:none;")

        self.inner = QWidget()
        self.inner.setAttribute(Qt.WA_TranslucentBackground, True)
        self.column = QVBoxLayout(self.inner)
        self.column.setContentsMargins(20, 18, 20, 20)
        self.column.setSpacing(12)
        self.scroll.setWidget(self.inner)
        root.addWidget(self.scroll, 1)

        # ---------------- 头部（一次性建好） ----------------
        self.header = QWidget(self.inner)
        head_layout = QHBoxLayout(self.header)
        head_layout.setContentsMargins(2, 0, 2, 0)
        head_layout.setSpacing(12)

        text_column = QVBoxLayout()
        text_column.setSpacing(4)
        self.code_label = QLabel(self.header)
        self.code_label.setFont(code_font(23, bold=True))
        text_column.addWidget(self.code_label)

        self.name_label = QLabel(self.header)
        self.name_label.setFont(ui_font(12, bold=True))
        self.name_label.setWordWrap(True)
        text_column.addWidget(self.name_label)
        head_layout.addLayout(text_column, 1)

        self.favorite_button = QToolButton(self.header)
        self.favorite_button.setFixedSize(36, 34)
        self.favorite_button.setCursor(QCursor(Qt.PointingHandCursor))
        self.favorite_button.setToolTip("收藏（Ctrl+D）")
        self.favorite_button.clicked.connect(self.favorite_requested.emit)
        head_layout.addWidget(self.favorite_button, alignment=Qt.AlignTop)

        self.copy_button = QToolButton(self.header)
        self.copy_button.setText("⧉")
        self.copy_button.setToolTip("复制整条（Ctrl+C）")
        self.copy_button.setFixedSize(36, 34)
        self.copy_button.setCursor(QCursor(Qt.PointingHandCursor))
        self.copy_button.clicked.connect(self.copy_requested.emit)
        head_layout.addWidget(self.copy_button, alignment=Qt.AlignTop)

        self.column.addWidget(self.header)

        # ---------------- 4 个预建分区 ----------------
        self.sections = {}  # type: Dict[str, Section]
        for title in SECTION_ORDER:
            section = Section(title, theme, features, on_copy=on_copy, parent=self.inner)
            self.sections[title] = section
            self.column.addWidget(section)

        self.empty_hint = EmptyHint(theme, self.inner)
        self.column.addWidget(self.empty_hint)
        self.column.addStretch(1)

        self.apply_theme(theme)
        self.set_data(None)

    # ---------------------------------------------------------- 数据
    def set_data(self, record, keyword="", is_favorite=False):
        # type: (Optional[Dict[str, Any]], str, bool) -> None
        self.current = record
        self.keyword = keyword or ""

        if record is None:
            self.header.setVisible(False)
            for section in self.sections.values():
                section.setVisible(False)
            self.empty_hint.setVisible(True)
            return

        self.empty_hint.setVisible(False)
        self.header.setVisible(True)

        theme = self.theme
        display_code = str(record.get("display_code") or record.get("stop_code") or "")
        self.code_label.setText(_highlight_html(display_code, self.keyword, theme))
        self.code_label.setStyleSheet(
            "color:%s;background:transparent;border:none;" % theme["code"]
        )
        self.name_label.setText(
            _highlight_html(str(record.get("name") or ""), self.keyword, theme)
        )
        self.name_label.setStyleSheet(
            "color:%s;background:transparent;border:none;" % theme["text"]
        )
        self.set_favorite(is_favorite)

        for title in SECTION_ORDER:
            section = self.sections[title]
            field_name = SECTION_FIELDS[title]
            section.setVisible(True)
            section.set_content(
                record.get(field_name),
                keyword=self.keyword,
                as_steps=(title == "排查步骤"),
            )

        self.scroll.verticalScrollBar().setValue(0)

    def set_favorite(self, is_favorite):
        # type: (bool) -> None
        self.favorite_button.setText("★" if is_favorite else "☆")
        color = self.theme["accent"] if is_favorite else self.theme["dim"]
        self.favorite_button.setStyleSheet(
            "QToolButton{background:transparent;border:none;color:%s;font-size:15px;}"
            "QToolButton:hover{background:%s;border-radius:10px;}"
            % (color, self.theme["chip"])
        )

    def plain_text_for_copy(self):
        # type: () -> str
        """整条记录的可复制纯文本。"""
        record = self.current
        if not record:
            return ""
        display_code = str(record.get("display_code") or record.get("stop_code") or "")
        lines = [
            "【%s】%s" % (display_code, str(record.get("name") or "")),
        ]
        for title in SECTION_ORDER:
            section = self.sections[title]
            lines.append("%s：%s" % (title, section.plain_text()))
        return "\n".join(lines)

    # ---------------------------------------------------------- 主题
    def apply_theme(self, theme):
        self.theme = theme
        self.scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}" + scrollbar_qss(theme)
        )
        self.inner.setStyleSheet("background:transparent;")
        for section in self.sections.values():
            section.apply_theme(theme)
        self.empty_hint.apply_theme(theme)
        self.set_favorite(
            bool(self.current) and self.favorite_button.text() == "★"
        )
        if self.current is not None:
            # 字号可能变了：重设字体后按新主题重渲染一次内容
            self.code_label.setFont(code_font(23, bold=True))
            self.name_label.setFont(ui_font(12, bold=True))
            self.code_label.setStyleSheet(
                "color:%s;background:transparent;border:none;" % theme["code"]
            )
            self.name_label.setStyleSheet(
                "color:%s;background:transparent;border:none;" % theme["text"]
            )
            self.set_data(
                self.current,
                keyword=self.keyword,
                is_favorite=self.favorite_button.text() == "★",
            )
        self.update()

    def paintEvent(self, event):
        theme = self.theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(qc(theme["border"]), 1.0))
        painter.setBrush(qc(theme["panel"]))
        painter.drawPath(rounded(rect, 20))
