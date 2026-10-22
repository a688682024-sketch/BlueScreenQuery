# -*- coding: utf-8 -*-
"""UI 层公开接口。"""

from .features import AppFeatures, os_architecture, os_label, windows_build
from .main_window import MainWindow, create_app, default_records
from .theme import SECTION_FIELDS, SECTION_ORDER, THEMES, get_theme

__all__ = [
    "AppFeatures",
    "MainWindow",
    "SECTION_FIELDS",
    "SECTION_ORDER",
    "THEMES",
    "create_app",
    "default_records",
    "get_theme",
    "os_architecture",
    "os_label",
    "windows_build",
]
