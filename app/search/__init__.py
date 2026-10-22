# -*- coding: utf-8 -*-
"""搜索层公开接口。

外部只需 ``from app.search import SearchIndex, prepare``。
"""

from .engine import (
    MAX_RESULTS,
    SearchIndex,
    SearchResult,
)
from .normalize import (
    KIND_EMPTY,
    KIND_HEX,
    KIND_TEXT,
    MAX_QUERY_LEN,
    Query,
    normalize_code,
    prepare,
)

__all__ = [
    "KIND_EMPTY",
    "KIND_HEX",
    "KIND_TEXT",
    "MAX_QUERY_LEN",
    "MAX_RESULTS",
    "Query",
    "SearchIndex",
    "SearchResult",
    "normalize_code",
    "prepare",
]
