# -*- coding: utf-8 -*-
"""主题令牌（沿用 v4 的配色数值，不改动审美）

只做两件事：
1. 提供 dark / light 两套令牌 + ``qc``/``mix`` 颜色工具；
2. 提供把令牌拼成 QSS 片段的辅助函数，减少各处重复字符串。

主题色值全部照搬 v4，属于必须保留的视觉资产。
"""

import re

from PySide2.QtGui import QColor

THEMES = {
    "dark": dict(
        key="dark",
        bg=("#090818", "#161233", "#0A0A1E"),
        text="#EEECFB",
        dim="rgba(238,236,251,0.60)",
        faint="rgba(238,236,251,0.32)",
        accent="#8B7CF8",
        accent2="#22D3EE",
        code="#A9B6FF",
        glass="rgba(255,255,255,0.045)",
        glass_hi="rgba(255,255,255,0.10)",
        sel="rgba(139,124,248,0.20)",
        border="rgba(255,255,255,0.09)",
        hair="rgba(255,255,255,0.055)",
        mark_bg="rgba(139,124,248,0.42)",
        mark_fg="#FFFFFF",
        chip="rgba(255,255,255,0.065)",
        panel="rgba(12,11,28,0.55)",
        shadow="rgba(0,0,0,0.5)",
        sc_bg="rgba(255,255,255,0.02)",
        sc_h="rgba(255,255,255,0.14)",
        sc_hh="rgba(255,255,255,0.24)",
        input_bg="rgba(255,255,255,0.055)",
        input_f="rgba(255,255,255,0.095)",
        danger="#E11D48",
        grain=0.030,
        sec={
            "含义": "#4ADE80",
            "通俗解释": "#FBBF24",
            "技术分析": "#60A5FA",
            "排查步骤": "#FB7185",
        },
    ),
    "light": dict(
        key="light",
        bg=("#F6F6FC", "#E9EAFA", "#FFFFFF"),
        text="#171640",
        dim="rgba(23,22,64,0.64)",
        faint="rgba(23,22,64,0.40)",
        accent="#5B4BE8",
        accent2="#0891B2",
        code="#4F46E5",
        glass="rgba(255,255,255,0.70)",
        glass_hi="rgba(255,255,255,0.94)",
        sel="rgba(91,75,232,0.13)",
        border="rgba(23,22,64,0.10)",
        hair="rgba(23,22,64,0.07)",
        mark_bg="rgba(91,75,232,0.26)",
        mark_fg="#171640",
        chip="rgba(23,22,64,0.05)",
        panel="rgba(255,255,255,0.72)",
        shadow="rgba(23,22,64,0.10)",
        sc_bg="rgba(23,22,64,0.03)",
        sc_h="rgba(23,22,64,0.18)",
        sc_hh="rgba(23,22,64,0.30)",
        input_bg="rgba(255,255,255,0.90)",
        input_f="#FFFFFF",
        danger="#BE123C",
        grain=0.014,
        sec={
            "含义": "#15803D",
            "通俗解释": "#B45309",
            "技术分析": "#1D4ED8",
            "排查步骤": "#BE123C",
        },
    ),
}

# 详情分区固定顺序（4 个预建分区，零 widget 重建）
SECTION_ORDER = ("含义", "通俗解释", "技术分析", "排查步骤")

# 分区名 -> 记录字段
SECTION_FIELDS = {
    "含义": "description",
    "通俗解释": "humor_desc",
    "技术分析": "pro_desc",
    "排查步骤": "solutions",
}


def get_theme(key):
    # type: (str) -> dict
    return THEMES.get(key) or THEMES["dark"]


def qc(spec, alpha=1.0):
    # type: (object, float) -> QColor
    """把 '#RRGGBB' / 'rgba(r,g,b,a)' 解析成 QColor，并叠加额外透明度。"""
    color = QColor()
    text = str(spec).strip()
    if text.startswith("rgb(") or text.startswith("rgba("):
        numbers = re.findall(r"[\d.]+", text)
        if len(numbers) >= 3:
            extra = float(numbers[3]) if len(numbers) > 3 else 1.0
            color.setRgbF(
                float(numbers[0]) / 255.0,
                float(numbers[1]) / 255.0,
                float(numbers[2]) / 255.0,
                max(0.0, min(1.0, extra * alpha)),
            )
            return color
    color.setNamedColor(text)
    if alpha < 1.0:
        color.setAlphaF(max(0.0, min(1.0, color.alphaF() * alpha)))
    return color


def mix(first, second, ratio):
    # type: (QColor, QColor, float) -> QColor
    ratio = max(0.0, min(1.0, float(ratio)))
    return QColor(
        int(first.red() + (second.red() - first.red()) * ratio),
        int(first.green() + (second.green() - first.green()) * ratio),
        int(first.blue() + (second.blue() - first.blue()) * ratio),
        int(first.alpha() + (second.alpha() - first.alpha()) * ratio),
    )


def scrollbar_qss(theme):
    # type: (dict) -> str
    return (
        "QScrollBar:vertical{background:%s;width:8px;margin:0;border:none;}"
        "QScrollBar::handle:vertical{background:%s;border-radius:4px;"
        "min-height:36px;border:none;}"
        "QScrollBar::handle:vertical:hover{background:%s;}"
        "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{"
        "background:transparent;}"
        % (theme["sc_bg"], theme["sc_h"], theme["sc_hh"])
    )


def plain_text_qss(theme, color_key="text"):
    # type: (dict, str) -> str
    return "color:%s;background:transparent;border:none;" % theme[color_key]
