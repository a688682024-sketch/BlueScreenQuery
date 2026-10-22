# -*- coding: utf-8 -*-
"""设置对话框：主题 / 字号 / 数据版本 / 清除历史 / 收藏导入导出 / 更新包

设计上把「业务动作」与「文件选择框」拆开：
``do_clear_history`` / ``do_export`` / ``do_import`` / ``do_update`` 接受
显式路径与 ``confirm`` 参数，可以直接在测试里调用；
按钮回调只负责弹 ``QFileDialog`` 与 ``QMessageBox``。
"""

import os
from typing import Any, Dict, Optional

from PySide2.QtCore import Qt, Signal
from PySide2.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..datasource import updater
from ..transfer import TransferError, export_favorites, import_favorites
from .theme import get_theme

FONT_MIN = 8
FONT_MAX = 16


def _default_schema_path():
    # type: () -> str
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "data", "schema.sql")


def _default_db_path():
    # type: () -> str
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from .. import resources

    return resources.runtime_db_path()


class SettingsDialog(QDialog):
    """设置窗口。``changed`` 在主窗口需要刷新时发出。"""

    changed = Signal()

    def __init__(
        self,
        repo,
        features,
        theme_key="dark",
        font_size=10,
        data_version="2.0",
        record_count=0,
        db_path=None,
        schema_path=None,
        parent=None,
    ):
        # type: (Any, Any, str, int, str, int, Optional[str], Optional[str], object) -> None
        super().__init__(parent)
        self.repo = repo
        self.features = features
        self.theme_key = theme_key
        self.font_size = font_size
        self.data_version = data_version
        self.record_count = record_count
        self.db_path = db_path or _default_db_path()
        self.schema_path = schema_path or _default_schema_path()

        self.setWindowTitle("设置")
        self.setMinimumWidth(460)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        title = QLabel("设置", self)
        title.setObjectName("settingsTitle")
        layout.addWidget(title)

        # ---------------- 外观 ----------------
        self.theme_combo = QComboBox(self)
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.addItem("浅色", "light")
        self.theme_combo.setCurrentIndex(0 if theme_key == "dark" else 1)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        layout.addWidget(self._row("主题", self.theme_combo))

        self.font_spin = QSpinBox(self)
        self.font_spin.setRange(FONT_MIN, FONT_MAX)
        self.font_spin.setValue(int(font_size))
        self.font_spin.valueChanged.connect(self._on_font_changed)
        layout.addWidget(self._row("界面字号", self.font_spin))

        # ---------------- 信息 ----------------
        self.info_label = QLabel("", self)
        self.info_label.setWordWrap(True)
        self.info_label.setObjectName("settingsInfo")
        layout.addWidget(self.info_label)

        # ---------------- 数据操作 ----------------
        layout.addWidget(self._section_title("数据"))
        buttons = QWidget(self)
        button_layout = QVBoxLayout(buttons)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(8)

        self.clear_history_button = QPushButton("清除搜索历史", buttons)
        self.clear_history_button.clicked.connect(self._on_clear_history)
        button_layout.addWidget(self.clear_history_button)

        self.export_button = QPushButton("导出收藏为 JSON…", buttons)
        self.export_button.clicked.connect(self._on_export)
        button_layout.addWidget(self.export_button)

        self.import_button = QPushButton("从 JSON 导入收藏…", buttons)
        self.import_button.clicked.connect(self._on_import)
        button_layout.addWidget(self.import_button)

        self.update_button = QPushButton("导入离线数据更新包…", buttons)
        self.update_button.clicked.connect(self._on_update)
        button_layout.addWidget(self.update_button)
        layout.addWidget(buttons)

        # ---------------- 关闭 ----------------
        footer = QWidget(self)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 8, 0, 0)
        footer_layout.addStretch(1)
        self.close_button = QPushButton("关闭", footer)
        self.close_button.clicked.connect(self.accept)
        footer_layout.addWidget(self.close_button)
        layout.addWidget(footer)

        self.refresh_info()
        self.apply_theme(theme_key)

    # ------------------------------------------------------------ 构件
    def _row(self, label_text, control):
        # type: (str, object) -> QWidget
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text, row)
        label.setMinimumWidth(88)
        layout.addWidget(label)
        layout.addWidget(control, 1)
        return row

    def _section_title(self, text):
        # type: (str) -> QLabel
        label = QLabel(text, self)
        label.setObjectName("settingsSection")
        return label

    # ------------------------------------------------------------ 主题
    def apply_theme(self, theme_key):
        # type: (str) -> None
        theme = get_theme(theme_key)
        self.setStyleSheet(
            "QDialog{background:%s;}"
            "QLabel{color:%s;background:transparent;}"
            "QLabel#settingsTitle{font-size:16px;font-weight:600;color:%s;}"
            "QLabel#settingsSection{color:%s;font-size:11px;font-weight:600;}"
            "QLabel#settingsInfo{color:%s;font-size:11px;}"
            "QComboBox,QSpinBox{background:%s;color:%s;border:1px solid %s;"
            "border-radius:8px;padding:4px 8px;min-height:22px;}"
            "QPushButton{background:%s;color:%s;border:1px solid %s;"
            "border-radius:9px;padding:7px 12px;text-align:left;}"
            "QPushButton:hover{background:%s;border-color:%s;}"
            % (
                theme["bg"][1],
                theme["text"],
                theme["text"],
                theme["faint"],
                theme["faint"],
                theme["input_bg"],
                theme["text"],
                theme["border"],
                theme["chip"],
                theme["text"],
                theme["border"],
                theme["sel"],
                theme["accent"],
            )
        )

    def _on_theme_changed(self, index):
        # type: (int) -> None
        self.theme_key = self.theme_combo.itemData(index) or "dark"
        self.apply_theme(self.theme_key)
        try:
            self.repo.set_setting("theme", self.theme_key)
        except Exception:
            pass
        self.changed.emit()

    def _on_font_changed(self, value):
        # type: (int) -> None
        self.font_size = int(value)
        try:
            self.repo.set_setting("font_size", self.font_size)
        except Exception:
            pass
        self.changed.emit()

    # ------------------------------------------------------------ 信息
    def refresh_info(self):
        # type: () -> None
        try:
            favorites = self.repo.favorite_count()
            history = self.repo.history_count()
        except Exception:
            favorites = 0
            history = 0
        text = "数据版本：v%s    内置记录：%d 条\n收藏：%d 条    历史：%d 条" % (
            self.data_version,
            int(self.record_count or 0),
            favorites,
            history,
        )
        self.info_label.setText(text)

    # ------------------------------------------------------------ 清除历史
    def do_clear_history(self, confirm=True):
        # type: (bool) -> int
        """清空历史，返回删除条数。``confirm`` 为真时先弹确认。"""
        if confirm:
            answer = QMessageBox.question(
                self,
                "确认清除",
                "确定要清除全部搜索历史吗？此操作不可撤销。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return 0
        removed = self.repo.clear_history()
        self.refresh_info()
        self.changed.emit()
        return removed

    def _on_clear_history(self):
        # type: () -> None
        removed = self.do_clear_history(confirm=True)
        if removed:
            QMessageBox.information(self, "已清除", "已清除 %d 条搜索历史。" % removed)

    # ------------------------------------------------------------ 导出
    def do_export(self, path):
        # type: (str) -> Dict[str, Any]
        stats = export_favorites(self.repo, path)
        self.refresh_info()
        return stats

    def _on_export(self):
        # type: () -> None
        from PySide2.QtWidgets import QFileDialog

        path, _selected = QFileDialog.getSaveFileName(
            self, "导出收藏", "bluescreen-favorites.json", "JSON 文件 (*.json)"
        )
        if not path:
            return
        try:
            stats = self.do_export(path)
        except TransferError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        QMessageBox.information(
            self, "导出完成", "已导出 %d 条收藏：\n%s" % (stats["count"], stats["path"])
        )

    # ------------------------------------------------------------ 导入
    def do_import(self, path, mode="merge", confirm=True):
        # type: (str, str, bool) -> Dict[str, Any]
        """导入收藏。``replace`` 模式必须二次确认。"""
        if mode == "replace" and confirm:
            answer = QMessageBox.question(
                self,
                "确认覆盖",
                "覆盖导入会先删除本地现有收藏，确定继续吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return {"mode": mode, "incoming": 0, "added": 0, "removed": 0, "total": 0}

        stats = import_favorites(self.repo, path, mode=mode)
        self.refresh_info()
        self.changed.emit()
        return stats

    def _on_import(self):
        # type: () -> None
        from PySide2.QtWidgets import QFileDialog

        path, _selected = QFileDialog.getOpenFileName(
            self, "导入收藏", "", "JSON 文件 (*.json)"
        )
        if not path:
            return

        box = QMessageBox(self)
        box.setWindowTitle("导入方式")
        box.setText("选择导入方式：合并会保留现有收藏，覆盖会先清空本地收藏。")
        merge_button = box.addButton("合并", QMessageBox.AcceptRole)
        replace_button = box.addButton("覆盖", QMessageBox.DestructiveRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec_()

        clicked = box.clickedButton()
        if clicked is merge_button:
            mode = "merge"
        elif clicked is replace_button:
            mode = "replace"
        else:
            return

        try:
            stats = self.do_import(path, mode=mode, confirm=True)
        except TransferError as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        if stats["incoming"] == 0:
            return
        QMessageBox.information(
            self,
            "导入完成",
            "方式：%s\n读取：%d 条\n新增：%d 条\n当前共：%d 条"
            % ("覆盖" if mode == "replace" else "合并", stats["incoming"], stats["added"], stats["total"]),
        )

    # ------------------------------------------------------------ 更新包
    def do_update(self, path, confirm=True):
        # type: (str, bool) -> Dict[str, Any]
        """应用离线更新包；失败抛 ``updater.UpdateError``。"""
        report = updater.validate_package(path)
        if not report["ok"]:
            raise updater.UpdateError(report["reason"])

        if confirm:
            answer = QMessageBox.question(
                self,
                "确认更新",
                "即将把内置数据更新到 v%s（%d 条）。\n更新前会自动备份当前数据。"
                % (report["version"], report["count"]),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return {}

        result = updater.apply_package(
            path, self.db_path, self.schema_path
        )
        self.data_version = result["version"]
        self.record_count = result["count"]
        self.refresh_info()
        self.changed.emit()
        return result

    def _on_update(self):
        # type: () -> None
        from PySide2.QtWidgets import QFileDialog

        path, _selected = QFileDialog.getOpenFileName(
            self, "选择更新包", "", "JSON 文件 (*.json)"
        )
        if not path:
            return
        try:
            result = self.do_update(path, confirm=True)
        except updater.UpdateError as exc:
            QMessageBox.warning(self, "更新失败", str(exc))
            return
        if not result:
            return
        QMessageBox.information(
            self,
            "更新完成",
            "内置数据已更新到 v%s，共 %d 条。\n备份：%s"
            % (result["version"], result["count"], result.get("backup") or "（原库不存在，无需备份）"),
        )
