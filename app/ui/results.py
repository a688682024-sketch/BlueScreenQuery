# -*- coding: utf-8 -*-
"""结果列表：数据模型 + 自绘 Delegate（虚拟化）

这是 v4 最不该动的资产，2.0 原样保留架构：

  QAbstractListModel + QListView + QStyledItemDelegate

无论 105 条还是 5 万条，屏幕上都只绘制可见的十余行；滚动与搜索成本恒定。
**不使用 QTableWidget**，也不做任何"每行一个 QWidget"的全量重建。

保留的 v4 视觉细节：
  行高 74、圆角 13、hover 淡入、会滑动的选中胶囊、左侧强调条、
  分阶段入场（stagger）、匹配度高亮、收藏星标。
"""

import math
import re
from typing import Any, Dict, List, Optional

from PySide2.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt
from PySide2.QtGui import QFontMetrics, QPainter, QPainterPath, QPen
from PySide2.QtWidgets import QStyledItemDelegate

from .theme import mix, qc
from .widgets import code_font, rounded, ui_font

ROW_HEIGHT = 74
ROW_RADIUS = 13.0
SPACE_RE = re.compile(r"\s+")


class CodeModel(QAbstractListModel):
    """只存两份平行列表：记录与分数。视图按需取用，不持有 widget。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []  # type: List[Dict[str, Any]]
        self.scores = []  # type: List[Optional[float]]

    def rowCount(self, parent=QModelIndex()):
        return len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self.items):
            return None
        if role == Qt.UserRole:
            return self.items[row]
        if role == Qt.UserRole + 1:
            return self.scores[row] if row < len(self.scores) else None
        return None

    def set_list(self, items, scores=None):
        # type: (List[Dict[str, Any]], Optional[List[float]]) -> None
        self.beginResetModel()
        self.items = list(items)
        if scores is None:
            self.scores = [None] * len(self.items)
        else:
            self.scores = list(scores)
        self.endResetModel()

    def item_at(self, row):
        # type: (int) -> Optional[Dict[str, Any]]
        if 0 <= row < len(self.items):
            return self.items[row]
        return None


def _draw_highlighted(painter, rect, text, keyword, color, font, theme, metrics=None):
    """先 elide 再分段高亮，保证不溢出、不触发二次布局。"""
    font_metrics = metrics or QFontMetrics(font)
    painter.setFont(font)
    shown = font_metrics.elidedText(str(text or ""), Qt.ElideRight, rect.width())
    painter.setPen(QPen(qc(color)))

    needle = (keyword or "").lower()
    if not needle:
        painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, shown)
        return

    position = shown.lower().find(needle)
    if position < 0:
        painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, shown)
        return

    prefix = shown[:position]
    middle = shown[position : position + len(needle)]
    suffix = shown[position + len(needle) :]

    x = rect.left()
    if prefix:
        width = font_metrics.width(prefix)
        painter.drawText(
            QRect(x, rect.top(), width, rect.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            prefix,
        )
        x += width

    middle_width = font_metrics.width(middle)
    highlight_height = min(rect.height(), font_metrics.height() + 4)
    highlight_y = rect.top() + (rect.height() - highlight_height) / 2
    painter.setPen(Qt.NoPen)
    painter.setBrush(qc(theme["mark_bg"]))
    painter.drawPath(
        rounded(
            QRectF(x - 2, highlight_y, middle_width + 4, highlight_height),
            4,
        )
    )
    painter.setPen(QPen(qc(theme["mark_fg"])))
    painter.drawText(
        QRect(int(x), rect.top(), middle_width, rect.height()),
        Qt.AlignVCenter | Qt.AlignLeft,
        middle,
    )
    x += middle_width

    if suffix:
        painter.setPen(QPen(qc(color)))
        painter.drawText(
            QRect(int(x), rect.top(), max(0, rect.right() - int(x)), rect.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            suffix,
        )


class ResultDelegate(QStyledItemDelegate):
    """自绘结果行：只画可见行，动画全部是 delegate 内的浮点量。"""

    def __init__(self, theme, view, features, parent=None):
        # type: (dict, object, object, object) -> None
        super().__init__(parent)
        self.theme = theme
        self.view = view
        self.features = features

        self.keyword = ""
        self.favorites = set()

        self.hover_row = -1
        self.hover_t = 0.0
        self.selected_from = -1
        self.selected_to = -1
        self.selected_t = 1.0
        self.intro = 1.0

        self.font_code = code_font(11, bold=True)
        self.font_name = ui_font(9, bold=True)
        self.font_desc = ui_font(8)
        self.font_score = code_font(8, bold=False)
        self._metrics_desc = QFontMetrics(self.font_desc)

    # ---------------------------------------------------------- 尺寸
    def sizeHint(self, option, index):
        return QSize(option.rect.width(), ROW_HEIGHT)

    # ---------------------------------------------------------- 绘制
    def paint(self, painter, option, index):
        theme = self.theme
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        item = index.data(Qt.UserRole)
        score = index.data(Qt.UserRole + 1)
        row = index.row()
        if item is None:
            painter.restore()
            return

        # 入场 stagger（关闭动效时 intro 恒为 1，直接跳过）
        if self.intro < 1.0:
            alpha = max(0.0, min(1.0, (self.intro - row * 0.045) / 0.4))
            if alpha <= 0.01:
                painter.restore()
                return
            painter.setOpacity(alpha)
            option.rect = option.rect.translated(0, int(14 * (1.0 - alpha)))

        rect = option.rect.adjusted(8, 4, -8, -4)

        # hover 底色
        is_hover = row == self.hover_row
        hover = self.hover_t if is_hover else 0.0
        background = mix(qc(theme["glass"]), qc(theme["glass_hi"]), hover)

        # 选中胶囊（从上一行滑到当前行）
        selection_rect = None
        selection_alpha = 0.0
        if self.selected_to >= 0:
            if row == self.selected_to:
                selection_alpha = self.selected_t
                selection_rect = rect
            elif row == self.selected_from and self.selected_t < 1.0:
                shifted = QRect(rect)
                offset = (self.selected_to - self.selected_from) * ROW_HEIGHT
                shifted.translate(0, int(offset * self.selected_t))
                selection_alpha = 1.0 - self.selected_t * 0.85
                selection_rect = shifted

        if selection_rect is not None and selection_alpha > 0.01:
            painter.setPen(Qt.NoPen)
            painter.setBrush(qc(theme["sel"], selection_alpha))
            painter.drawPath(rounded(selection_rect, ROW_RADIUS))
            painter.setPen(QPen(qc(theme["accent"], 0.55 * selection_alpha), 1.2))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(rounded(selection_rect, ROW_RADIUS))
            bar = QRect(
                int(selection_rect.left() + 6),
                int(selection_rect.top() + 14),
                3,
                int(selection_rect.height() - 28),
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(qc(theme["accent"], selection_alpha))
            painter.drawPath(rounded(bar, 1.5))
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(background)
            painter.drawPath(rounded(rect, ROW_RADIUS))
            if hover > 0.01:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(qc(theme["accent"], 0.16 * hover), 2.6))
                painter.drawPath(rounded(rect.adjusted(-1, -1, 1, 1), ROW_RADIUS + 1))

        # 收藏星标
        code = str(item.get("stop_code") or item.get("code") or "")
        is_favorite = code in self.favorites
        indent = 22 if is_favorite else 12
        if is_favorite:
            center_x = rect.left() + 11
            center_y = rect.top() + rect.height() / 2.0
            painter.setPen(Qt.NoPen)
            painter.setBrush(qc(theme["accent"]))
            star = QPainterPath()
            for index_vertex in range(10):
                angle = math.pi / 2 + index_vertex * math.pi / 5
                radius = 5.0 if index_vertex % 2 == 0 else 2.2
                x = center_x + radius * math.cos(angle)
                y = center_y - radius * math.sin(angle)
                if index_vertex == 0:
                    star.moveTo(x, y)
                else:
                    star.lineTo(x, y)
            star.closeSubpath()
            painter.drawPath(star)

        # 文本区
        text_rect = QRect(
            int(rect.left() + indent),
            int(rect.top() + 11),
            int(rect.width() - indent - 74),
            int(rect.height() - 22),
        )

        display_code = str(item.get("display_code") or item.get("stop_code") or "")
        _draw_highlighted(
            painter,
            QRect(text_rect.left(), text_rect.top(), text_rect.width(), 20),
            display_code,
            self.keyword,
            theme["code"],
            self.font_code,
            theme,
        )

        _draw_highlighted(
            painter,
            QRect(text_rect.left(), text_rect.top() + 21, text_rect.width(), 16),
            str(item.get("name") or ""),
            self.keyword,
            theme["text"],
            self.font_name,
            theme,
        )

        summary = str(item.get("description") or item.get("pro_desc") or "")
        summary = SPACE_RE.sub(" ", summary).strip()
        painter.setFont(self.font_desc)
        painter.setPen(QPen(qc(theme["faint"])))
        painter.drawText(
            QRect(text_rect.left(), text_rect.top() + 38, text_rect.width(), 16),
            Qt.AlignVCenter | Qt.AlignLeft,
            self._metrics_desc.elidedText(summary, Qt.ElideRight, text_rect.width()),
        )

        # 匹配度 chip
        if score is not None:
            painter.setFont(self.font_score)
            chip = QRect(int(rect.right() - 66), int(rect.top() + 24), 52, 20)
            painter.setPen(Qt.NoPen)
            painter.setBrush(qc(theme["chip"]))
            painter.drawPath(rounded(chip, 7))
            painter.setPen(QPen(qc(theme["faint"])))
            painter.drawText(chip, Qt.AlignCenter, "%d%%" % int(round(score * 100)))

        painter.restore()

    # ---------------------------------------------------------- 状态
    def apply_theme(self, theme):
        self.theme = theme
        self.font_code = code_font(11, bold=True)
        self.font_name = ui_font(9, bold=True)
        self.font_desc = ui_font(8)
        self.font_score = code_font(8, bold=False)
        self._metrics_desc = QFontMetrics(self.font_desc)
