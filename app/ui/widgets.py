# -*- coding: utf-8 -*-
"""基础自绘控件：标题栏、搜索框、Toast、空状态、状态栏、筛选栏

全部为 v4 视觉资产的延续，只做两处升级：
1. 动画时长统一由 ``AppFeatures`` 决定（关特效时立即为 0，静态完成）；
2. 状态栏按规格做 **100ms 节流**，避免高频搜索时文本狂闪。
"""

from PySide2.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide2.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide2.QtWidgets import QLineEdit, QPushButton, QWidget

from .theme import mix, qc

STATUS_THROTTLE_MS = 100

# 全局字体缩放：由设置面板的「界面字号」驱动，1.0 为基准（10pt）
FONT_SCALE = 1.0

_FONT_MIN = 6
_FONT_MAX = 34


def set_font_scale(scale):
    # type: (float) -> float
    """设置全局字体缩放并返回实际生效值（限制在 0.7~1.6）。"""
    global FONT_SCALE
    try:
        value = float(scale)
    except (TypeError, ValueError):
        value = 1.0
    FONT_SCALE = max(0.7, min(1.6, value))
    return FONT_SCALE


def scaled_size(size):
    # type: (float) -> int
    return max(_FONT_MIN, min(_FONT_MAX, int(round(float(size) * FONT_SCALE))))


def body_font_px():
    # type: () -> int
    """详情正文的像素字号（跟随全局缩放）。"""
    return max(10, min(40, int(round(13 * FONT_SCALE))))


def ui_font(size, bold=False):
    # type: (int, bool) -> QFont
    font = QFont()
    font.setPointSize(scaled_size(size))
    if bold:
        font.setWeight(QFont.DemiBold)
    return font


def code_font(size, bold=True):
    # type: (int, bool) -> QFont
    """代码字体：v4 用的是 Consolas，保持不变。"""
    font = QFont("Consolas")
    font.setPointSize(scaled_size(size))
    font.setBold(bold)
    return font


def rounded(rect, radius):
    # type: (object, float) -> QPainterPath
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), radius, radius)
    return path


def elided(font, text, width):
    # type: (QFont, str, int) -> str
    return QFontMetrics(font).elidedText(str(text or ""), Qt.ElideRight, max(0, width))


# =====================================================================
# 标题栏
# =====================================================================
class TitleBar(QWidget):
    """自绘标题栏：拖拽移动、双击最大化、最小/最大/关闭、主题切换。"""

    def __init__(self, theme, features, handlers=None, parent=None):
        # type: (dict, object, object, object) -> None
        super().__init__(parent)
        self.theme = theme
        self.features = features
        self.handlers = handlers or {}
        self._drag_offset = None
        self.setFixedHeight(44)
        self.setObjectName("titleBar")

        self.settings_button = QPushButton("⚙")
        self.settings_button.setCursor(QCursor(Qt.PointingHandCursor))
        self.settings_button.setToolTip("设置")
        self.settings_button.setFixedSize(32, 28)
        self.settings_button.clicked.connect(self._call("settings"))
        self.settings_button.setParent(self)

        self.theme_button = QPushButton("◐ 主题")
        self.theme_button.setCursor(QCursor(Qt.PointingHandCursor))
        self.theme_button.setFixedSize(78, 28)
        self.theme_button.clicked.connect(self._call("theme"))
        self.theme_button.setParent(self)

        self.min_button = QPushButton("—")
        self.max_button = QPushButton("□")
        self.close_button = QPushButton("✕")
        self.min_button.clicked.connect(self._call("min"))
        self.max_button.clicked.connect(self._call("max"))
        self.close_button.clicked.connect(self._call("close"))
        for button in (self.min_button, self.max_button, self.close_button):
            button.setCursor(QCursor(Qt.PointingHandCursor))
            button.setFixedSize(32, 28)
            button.setParent(self)

    def _call(self, key):
        def handler():
            callback = self.handlers.get(key)
            if callable(callback):
                callback()

        return handler

    # ---------------------------------------------------------- 布局
    def resizeEvent(self, event):
        super().resizeEvent(event)
        height = self.height()
        right = self.width() - 12
        self.close_button.move(right - 32, (height - 28) // 2)
        self.max_button.move(right - 68, (height - 28) // 2)
        self.min_button.move(right - 104, (height - 28) // 2)
        self.theme_button.move(right - 190, (height - 28) // 2)
        self.settings_button.move(right - 228, (height - 28) // 2)

    # ---------------------------------------------------------- 拖拽
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPos() - self.window().frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self.window().move(event.globalPos() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_offset = None

    def mouseDoubleClickEvent(self, event):
        callback = self.handlers.get("max")
        if callable(callback):
            callback()

    # ---------------------------------------------------------- 绘制
    def apply_theme(self, theme):
        self.theme = theme
        self.theme_button.setStyleSheet(
            "QPushButton{background:%s;color:%s;border:1px solid %s;"
            "border-radius:14px;font-size:11px;}"
            "QPushButton:hover{background:%s;border-color:%s;}"
            % (theme["chip"], theme["dim"], theme["border"], theme["sel"], theme["accent"])
        )
        for button in (self.min_button, self.max_button):
            button.setStyleSheet(
                "QPushButton{background:transparent;color:%s;border:none;font-size:12px;}"
                "QPushButton:hover{background:%s;border-radius:14px;}"
                % (theme["dim"], theme["chip"])
            )
        self.close_button.setStyleSheet(
            "QPushButton{background:transparent;color:%s;border:none;font-size:12px;}"
            "QPushButton:hover{background:%s;color:#FFFFFF;border-radius:14px;}"
            % (theme["dim"], theme["danger"])
        )
        self.settings_button.setStyleSheet(
            "QPushButton{background:transparent;color:%s;border:none;font-size:13px;}"
            "QPushButton:hover{background:%s;border-radius:14px;}"
            % (theme["dim"], theme["chip"])
        )
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setFont(ui_font(9, bold=True))
        painter.setPen(QPen(qc(self.theme["text"])))
        painter.drawText(
            QRect(16, 0, self.width() - 220, self.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            "蓝屏代码查询器 2.0",
        )


# =====================================================================
# 搜索框
# =====================================================================
class SearchBox(QLineEdit):
    """Hero 搜索框：放大镜 + 焦点光环 + 快捷键徽章 + 清除按钮。"""

    def __init__(self, theme, features, parent=None):
        # type: (dict, object, object) -> None
        super().__init__(parent)
        self.theme = theme
        self.features = features
        self._focus_level = 0.0
        self.setFixedHeight(50)
        self.setTextMargins(46, 0, 74, 0)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background:transparent;border:none;")

        self._animation = QPropertyAnimation(self, b"focus_level")
        self._animation.setDuration(features.duration_fast)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

    # ---------------------------------------------------------- 属性
    def _get_focus_level(self):
        return self._focus_level

    def _set_focus_level(self, value):
        self._focus_level = float(value)
        self.update()

    focus_level = Property(float, _get_focus_level, _set_focus_level)

    def _animate_focus(self, target):
        self._animation.stop()
        if not self.features.animations:
            self._set_focus_level(target)
            return
        self._animation.setStartValue(self._focus_level)
        self._animation.setEndValue(target)
        self._animation.start()

    def focusInEvent(self, event):
        self._animate_focus(1.0)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._animate_focus(0.0)
        super().focusOutEvent(event)

    # ---------------------------------------------------------- 清除按钮
    def _clear_rect(self):
        # type: () -> QRect
        rect = self.rect()
        return QRect(rect.right() - 34, rect.top() + (rect.height() - 22) // 2, 22, 22)

    def mousePressEvent(self, event):
        if self.text() and self._clear_rect().contains(event.pos()):
            self.clear()
            return
        super().mousePressEvent(event)

    # ---------------------------------------------------------- 主题
    def apply_theme(self, theme):
        self.theme = theme
        palette = self.palette()
        palette.setColor(self.palette().Text, qc(theme["text"]))
        palette.setColor(self.palette().PlaceholderText, qc(theme["faint"]))
        self.setPalette(palette)
        self.update()

    # ---------------------------------------------------------- 绘制
    def paintEvent(self, event):
        theme = self.theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(2, 2, -2, -2)
        radius = rect.height() / 2.0

        # 焦点光环
        if self._focus_level > 0.01:
            for index in range(3):
                alpha = 0.16 * self._focus_level * (1 - index * 0.28)
                painter.setPen(QPen(qc(theme["accent"], alpha), 3.0 + index * 3.5))
                painter.setBrush(Qt.NoBrush)
                spread = 1.5 + index * 1.6
                painter.drawPath(
                    rounded(
                        rect.adjusted(-spread, -spread, spread, spread),
                        radius + spread,
                    )
                )

        painter.setPen(Qt.NoPen)
        painter.setBrush(qc(theme["input_bg"]))
        painter.drawPath(rounded(rect, radius))

        border = mix(qc(theme["border"]), qc(theme["accent"]), self._focus_level)
        painter.setPen(QPen(border, 1.3 + self._focus_level * 0.7))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(rounded(rect, radius))

        # 放大镜
        center_x = rect.left() + 24
        center_y = rect.top() + rect.height() / 2.0
        painter.setPen(QPen(qc(theme["dim"]), 1.8))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(center_x, center_y - 1), 6.5, 6.5)
        painter.drawLine(
            QPointF(center_x + 4.6, center_y + 3.6),
            QPointF(center_x + 9.5, center_y + 8.5),
        )

        if not self.text():
            painter.setPen(Qt.NoPen)
            painter.setBrush(qc(theme["chip"]))
            badge = QRect(
                int(rect.right() - 60),
                int(rect.top() + (rect.height() - 20) / 2),
                46,
                20,
            )
            painter.drawPath(rounded(badge, 6))
            painter.setPen(QPen(qc(theme["faint"])))
            painter.setFont(code_font(8, bold=False))
            painter.drawText(badge, Qt.AlignCenter, "Ctrl+K")
        else:
            clear_rect = self._clear_rect()
            painter.setPen(Qt.NoPen)
            painter.setBrush(qc(theme["chip"]))
            painter.drawPath(rounded(clear_rect, 11))
            painter.setPen(QPen(qc(theme["dim"]), 1.5))
            painter.drawLine(
                QPointF(clear_rect.left() + 7, clear_rect.top() + 7),
                QPointF(clear_rect.right() - 7, clear_rect.bottom() - 7),
            )
            painter.drawLine(
                QPointF(clear_rect.right() - 7, clear_rect.top() + 7),
                QPointF(clear_rect.left() + 7, clear_rect.bottom() - 7),
            )

        super().paintEvent(event)


# =====================================================================
# Toast
# =====================================================================
class Toast(QWidget):
    """轻量提示条：鼠标穿透、定时淡出；关闭动效时改为瞬显瞬隐。"""

    def __init__(self, features, theme, parent=None):
        # type: (object, dict, object) -> None
        super().__init__(parent)
        self.features = features
        self.theme = theme
        self._text = ""
        self._opacity = 0.0
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._start_fade)

        self._ticker = QTimer(self)
        self._ticker.setInterval(16)
        self._ticker.timeout.connect(self._step)

    def show_message(self, text):
        # type: (str) -> None
        self._text = str(text)
        self._opacity = 0.0 if self.features.animations else 1.0
        self._reposition()
        self.show()
        self.raise_()
        if self.features.animations:
            self._ticker.start()
        else:
            self.update()
        self._hold.start(self.features.toast_duration)

    def _reposition(self):
        parent = self.parent()
        if parent is None:
            return
        self.setGeometry(0, max(0, parent.height() - 96), parent.width(), 44)

    @property
    def text(self):
        # type: () -> str
        return self._text

    def _start_fade(self):
        if not self.features.animations:
            self.hide()
            return
        self._fading = True

    def _step(self):
        if not self.features.animations:
            self._ticker.stop()
            return
        fading = getattr(self, "_fading", False)
        if fading:
            self._opacity -= 0.08
            if self._opacity <= 0.0:
                self._opacity = 0.0
                self._fading = False
                self._ticker.stop()
                self.hide()
                return
        else:
            self._opacity = min(1.0, self._opacity + 0.16)
        self.update()

    def apply_theme(self, theme):
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        if self._opacity <= 0.01:
            return
        theme = self.theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        width = min(360, self.width() - 48)
        rect = QRect((self.width() - width) // 2, 8, width, 34)
        painter.setPen(Qt.NoPen)
        painter.setBrush(qc(theme["panel"], min(1.0, self._opacity * 0.97)))
        painter.drawPath(rounded(rect, 10))
        painter.setPen(QPen(qc(theme["border"], self._opacity), 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(rounded(rect, 10))

        painter.setPen(Qt.NoPen)
        painter.setBrush(qc(theme["accent"], self._opacity))
        painter.drawEllipse(QPointF(rect.left() + 16, rect.center().y()), 3.5, 3.5)

        painter.setPen(QPen(qc(theme["text"], self._opacity)))
        painter.setFont(ui_font(9, bold=True))
        painter.drawText(
            rect.adjusted(28, 0, -14, 0),
            Qt.AlignVCenter | Qt.AlignLeft,
            elided(ui_font(9, bold=True), self._text, rect.width() - 46),
        )


# =====================================================================
# 空状态
# =====================================================================
class EmptyState(QWidget):
    """空 / 无结果 / 错误 三态插画；不显示任何伪造内容。"""

    def __init__(self, theme, parent=None):
        # type: (dict, object) -> None
        super().__init__(parent)
        self.theme = theme
        self.kind = "empty"
        self.title = "输入开始查询"
        self.subtitle = "支持代码（0x0000007B / 7b）、英文名或中文症状"
        self.setMinimumHeight(260)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def set_state(self, kind, title, subtitle):
        # type: (str, str, str) -> None
        self.kind = kind
        self.title = title
        self.subtitle = subtitle
        self.update()

    def paintEvent(self, event):
        theme = self.theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        center_x = self.width() / 2.0
        center_y = self.height() / 2.0 - 26

        color = {
            "empty": theme["accent"],
            "noresult": theme["accent2"],
            "error": theme["danger"],
        }.get(self.kind, theme["accent"])

        for index in range(3):
            painter.setPen(QPen(qc(color, 0.22 - index * 0.06), 1.4))
            painter.setBrush(Qt.NoBrush)
            radius = 30 + index * 16
            painter.drawEllipse(QPointF(center_x, center_y), radius, radius)

        painter.setPen(QPen(qc(color, 0.85), 2.2))
        if self.kind == "error":
            painter.drawLine(
                QPointF(center_x - 8, center_y - 8), QPointF(center_x + 8, center_y + 8)
            )
            painter.drawLine(
                QPointF(center_x + 8, center_y - 8), QPointF(center_x - 8, center_y + 8)
            )
        else:
            painter.drawEllipse(QPointF(center_x, center_y), 19, 19)
            painter.drawLine(
                QPointF(center_x + 13, center_y + 13),
                QPointF(center_x + 28, center_y + 28),
            )

        painter.setPen(QPen(qc(theme["text"])))
        title_font = ui_font(12, bold=True)
        painter.setFont(title_font)
        painter.drawText(
            QRect(0, int(center_y + 58), self.width(), 26), Qt.AlignCenter, self.title
        )

        painter.setPen(QPen(qc(theme["faint"])))
        sub_font = ui_font(9)
        painter.setFont(sub_font)
        painter.drawText(
            QRect(24, int(center_y + 86), self.width() - 48, 44),
            Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
            self.subtitle,
        )


# =====================================================================
# 底部状态栏（100ms 节流）
# =====================================================================
class StatusBar(QWidget):
    """底部三区状态栏：左=搜索状态 / 中=数据版本 / 右=免责声明。

    规格要求「100ms 节流的文本更新」——高频搜索时若每次输入都改文本，
    标签会疯狂重排并闪烁。这里把更新合并到一个 100ms 的单次定时器里，
    最多每 100ms 刷新一次 UI，且同周期内的多次调用只保留最后一次的值。
    """

    def __init__(self, theme, parent=None):
        # type: (dict, object) -> None
        super().__init__(parent)
        self.theme = theme
        self.setFixedHeight(30)

        self._left = "就绪"
        self._middle = ""
        self._right = "仅供参考，不替代官方支持"
        self._pending = None  # type: object

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(STATUS_THROTTLE_MS)
        self._timer.timeout.connect(self._flush)

        # 便于验证节流是否生效
        self.flush_count = 0

    # ---------------------------------------------------------- 对外
    def set_texts(self, left=None, middle=None, right=None):
        # type: (object, object, object) -> None
        pending = self._pending
        if pending is None:
            pending = (self._left, self._middle, self._right)
        merged = (
            pending[0] if left is None else str(left),
            pending[1] if middle is None else str(middle),
            pending[2] if right is None else str(right),
        )
        self._pending = merged
        if not self._timer.isActive():
            self._timer.start()

    def flush_now(self):
        # type: () -> None
        """立即应用挂起的文本（测试与关窗时使用）。"""
        self._timer.stop()
        self._flush()

    def _flush(self):
        if self._pending is None:
            return
        self._left, self._middle, self._right = self._pending
        self._pending = None
        self.flush_count += 1
        self.update()

    # ---------------------------------------------------------- 属性
    @property
    def left_text(self):
        # type: () -> str
        return self._left

    @property
    def middle_text(self):
        # type: () -> str
        return self._middle

    @property
    def right_text(self):
        # type: () -> str
        return self._right

    def apply_theme(self, theme):
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        theme = self.theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        left_font = code_font(8, bold=False)
        norm_font = ui_font(8)
        rect = self.rect().adjusted(24, 0, -24, 0)

        # 左：搜索状态
        painter.setFont(left_font)
        painter.setPen(QPen(qc(theme["dim"])))
        left_width = max(120, int(rect.width() * 0.34))
        painter.drawText(
            QRect(rect.left(), 0, left_width, self.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            elided(left_font, self._left, left_width),
        )

        # 中：数据版本（居中）
        painter.setFont(norm_font)
        painter.setPen(QPen(qc(theme["faint"])))
        if self._middle:
            painter.drawText(
                QRect(rect.left() + left_width, 0, rect.width() - left_width * 2, self.height()),
                Qt.AlignCenter,
                elided(norm_font, self._middle, rect.width() - left_width * 2),
            )

        # 右：免责声明
        right_width = int(rect.width() * 0.34)
        painter.drawText(
            QRect(rect.right() - right_width, 0, right_width, self.height()),
            Qt.AlignVCenter | Qt.AlignRight,
            elided(norm_font, self._right, right_width),
        )


# =====================================================================
# 左侧筛选栏
# =====================================================================
class FilterColumn(QWidget):
    """左侧筛选：全部 / 收藏 / 最近，带计数，可折叠。"""

    MODES = (("all", "全部"), ("favorite", "收藏"), ("recent", "最近"))
    changed = Signal(str)

    def __init__(self, theme, features, parent=None):
        # type: (dict, object, object) -> None
        super().__init__(parent)
        self.theme = theme
        self.features = features
        self.mode = "all"
        self.counts = {"all": 0, "favorite": 0, "recent": 0}
        self._hover = -1
        self.setMouseTracking(True)
        self.setFixedWidth(190)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def set_counts(self, total, favorites, recent):
        # type: (int, int, int) -> None
        self.counts = {
            "all": int(total),
            "favorite": int(favorites),
            "recent": int(recent),
        }
        self.update()

    def set_mode(self, mode):
        # type: (str) -> None
        if mode == self.mode:
            return
        self.mode = mode
        self.update()
        self.changed.emit(mode)

    # ---------------------------------------------------------- 几何
    def _rows(self):
        # type: () -> list
        rows = []
        top = 52
        height = 40
        for index in range(len(self.MODES)):
            rows.append(QRect(10, top + index * (height + 6), self.width() - 20, height))
        return rows

    def mousePressEvent(self, event):
        for index, rect in enumerate(self._rows()):
            if rect.contains(event.pos()):
                self.set_mode(self.MODES[index][0])
                return

    def mouseMoveEvent(self, event):
        hover = -1
        for index, rect in enumerate(self._rows()):
            if rect.contains(event.pos()):
                hover = index
                break
        if hover != self._hover:
            self._hover = hover
            self.update()

    def leaveEvent(self, event):
        if self._hover != -1:
            self._hover = -1
            self.update()

    def apply_theme(self, theme):
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        theme = self.theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        painter.setFont(ui_font(9, bold=True))
        painter.setPen(QPen(qc(theme["faint"])))
        painter.drawText(
            QRect(14, 20, self.width() - 28, 24),
            Qt.AlignVCenter | Qt.AlignLeft,
            "筛选",
        )

        for index, (key, label) in enumerate(self.MODES):
            rect = self._rows()[index]
            active = self.mode == key
            if active:
                painter.setPen(Qt.NoPen)
                painter.setBrush(qc(theme["sel"]))
                painter.drawPath(rounded(rect, 10))
                painter.setPen(QPen(qc(theme["accent"], 0.55), 1.2))
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(rounded(rect, 10))
            elif index == self._hover:
                painter.setPen(Qt.NoPen)
                painter.setBrush(qc(theme["glass"]))
                painter.drawPath(rounded(rect, 10))

            painter.setFont(ui_font(10, bold=active))
            painter.setPen(QPen(qc(theme["text"] if active else theme["dim"])))
            painter.drawText(
                rect.adjusted(14, 0, -52, 0),
                Qt.AlignVCenter | Qt.AlignLeft,
                label,
            )

            painter.setFont(code_font(9, bold=False))
            painter.setPen(QPen(qc(theme["faint"])))
            painter.drawText(
                rect.adjusted(0, 0, -14, 0),
                Qt.AlignVCenter | Qt.AlignRight,
                str(self.counts.get(key, 0)),
            )
