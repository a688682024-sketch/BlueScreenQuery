# -*- coding: utf-8 -*-
"""查询规范化（2.0 搜索层入口）

这一层只做「把用户输入变成可比对的形式」，不含任何数据检索逻辑，
便于单测，也便于将来接 UI 时复用。

规范化规则（与产品规格逐条对应）
--------------------------------
1. 去除首尾空白、压缩内部连续空白；连字符（- ‐ – —）视同空白丢弃。
2. 十六进制字母统一大写；``0x`` / ``0X`` 前缀归一为一个 ``0X``。
3. 纯十六进制且无前缀时，按「补零到 8 位」得到主键，从而
   ``0x0000007B`` / ``7b`` / ``0X7B`` / ``0000007B`` 全部指向同一条记录。
4. 名称、别名、描述一律走大小写不敏感包含匹配（由 SearchIndex 负责）。
5. 输入超过 ``MAX_QUERY_LEN`` 时截断并置 ``truncated``，供 UI 提示。
6. 空输入不抛错，返回 ``kind == "empty"``，由 UI 决定展示历史/收藏/示例。

与 ``app.datasource.migrate.normalize_code`` 的关系
---------------------------------------------------
两者必须给出同样的主键。为避免悄悄分叉，``tests/test_search.py`` 里有一条
一致性测试逐样本比对两边结果；任一侧改动导致不一致会立即失败。
"""

import re
from typing import Any, NamedTuple, Optional

MAX_QUERY_LEN = 256

KIND_EMPTY = "empty"
KIND_HEX = "hex"
KIND_TEXT = "text"

_WS_RE = re.compile(r"\s+")
_DASH_RE = re.compile(r"[-\u2010\u2011\u2012\u2013\u2014\u2015]")
_HEX_ONLY_RE = re.compile(r"^[0-9A-F]+$")


class Query(NamedTuple):
    """一次查询的规范化结果（不可变，可安全缓存）。"""

    raw: str        # 用户原始输入
    text: str       # 去首尾空白 + 压缩空白后的文本
    needle: str     # 小写文本，用于大小写不敏感包含匹配
    kind: str       # "empty" / "hex" / "text"
    hex_raw: str    # 十六进制体原样（大写、无 0X），如 "7B" / "0000013"
    hex_sig: str    # 去前导零的显著位，如 "7B"（全零时保留 "0"）
    truncated: bool     # 是否因超长被截断

    @property
    def is_empty(self):
        # type: () -> bool
        return self.kind == KIND_EMPTY

    @property
    def is_hex(self):
        # type: () -> bool
        return self.kind == KIND_HEX

    @property
    def hex_prefix_mode(self):
        # type: () -> bool
        """是否按「前缀」理解这次十六进制查询。

        用户自己敲了前导零（``0000013``）表示"我要以 0000013 开头的代码"，
        此时必须做前缀比较；若硬补零成 8 位会在数字中间插零、语义全错。

        没敲前导零（``7B``）则按蓝屏码惯例做数值比较——``0x7B`` 就是
        ``0x0000007B``，靠显著位对齐。
        单字符（``0x0``）不进前缀模式，否则会匹配全部代码。
        """
        return len(self.hex_raw) >= 2 and self.hex_raw.startswith("0")


def _compact(text):
    # type: (str) -> str
    """去掉空白与连字符并转大写。"""
    return _DASH_RE.sub("", _WS_RE.sub("", text)).upper()


def normalize_code(raw):
    # type: (Any) -> str
    """规范化停止代码为 ``0X`` + 8 位大写十六进制；无法识别时返回空串。

    与 ``migrate.normalize_code`` 保持同一契约，便于两边结果互校。
    """
    if raw is None:
        return ""
    compact = _compact(str(raw))
    if compact.startswith("0X"):
        compact = compact[2:]
    if not compact or not _HEX_ONLY_RE.match(compact):
        return ""
    significant = compact.lstrip("0") or "0"
    return "0X" + significant.zfill(8)


def prepare(raw):
    # type: (Optional[str]) -> Query
    """把任意用户输入整理成 ``Query``；永不抛异常。"""
    original = "" if raw is None else str(raw)
    text = _WS_RE.sub(" ", original).strip()

    truncated = len(text) > MAX_QUERY_LEN
    if truncated:
        text = text[:MAX_QUERY_LEN]

    if not text:
        return Query(original, "", "", KIND_EMPTY, "", "", truncated)

    needle = text.lower()
    compact = _compact(text)

    # 代码形态：去掉空白/连字符后全是十六进制字符
    body = compact[2:] if compact.startswith("0X") else compact
    looks_hex = bool(body) and bool(_HEX_ONLY_RE.match(body))

    # 无前缀时至少两位才认定为代码，避免把单个 "A" 当成代码
    if looks_hex and (compact.startswith("0X") or len(body) >= 2):
        significant = body.lstrip("0") or "0"
        return Query(
            original,
            text,
            needle,
            KIND_HEX,
            body,
            significant,
            truncated,
        )

    return Query(original, text, needle, KIND_TEXT, "", "", truncated)
