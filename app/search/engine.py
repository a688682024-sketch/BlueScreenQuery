# -*- coding: utf-8 -*-
"""搜索索引与三段式检索引擎

沿用 v4 已验证的性能架构（这是本项目最不该动的资产）：

  第一段  十六进制精确/前缀通道   —— O(n) 但常数极小，只比较预计算字段
  第二段  子串快速通道           —— 名称/别名/描述等预转小写后的 ``in`` 判断
  第三段  模糊兜底               —— 仅当结果稀少时才跑 SequenceMatcher

每次查询结果进 LRU 缓存；纯内存、无 SQL、无阻塞。

相关性排序（产品规格 §P1 的落地）
---------------------------------
  1.00  停止代码精确命中（含补零等价）
  0.96  停止代码前缀命中
  0.92  名称完全相等
  0.90  别名完全相等
  0.88  停止代码包含
  0.78  名称包含
  0.70  定义（description）包含
  0.62  比喻段（humor_desc）包含
  0.58  技术段（pro_desc）包含
  0.52  常见原因（causes）包含
  0.46  排查步骤（solutions）包含

即：精确代码 > 代码前缀 > 别名精确 > 名称包含 > 描述包含。
"""

import json
import re
from collections import OrderedDict
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Tuple

from .normalize import KIND_EMPTY, Query, prepare

MAX_RESULTS = 200
DEFAULT_CACHE_SIZE = 64
DEFAULT_FUZZY_CACHE = 256

# 相关性权重（集中定义，便于调参与测试）
S_CODE_EXACT = 1.00
S_CODE_PREFIX = 0.96
S_NAME_EXACT = 0.92
S_ALIAS_EXACT = 0.90
S_CODE_CONTAINS = 0.88
S_NAME_CONTAINS = 0.78
S_DESC_CONTAINS = 0.70
S_HUMOR_CONTAINS = 0.62
S_PRO_CONTAINS = 0.58
S_CAUSE_CONTAINS = 0.52
S_SOLUTION_CONTAINS = 0.46

# 模糊兜底的触发条件
FUZZY_MIN_RESULTS = 4        # 已有足够结果就不跑模糊
FUZZY_MIN_NEEDLE = 2
FUZZY_MAX_NEEDLE = 48        # 名称可能很长（INACCESSIBLE_BOOT_DEVICE 有 24 字符）
FUZZY_RAW_THRESHOLD = 0.70   # 先判原始相似度，避免被权重压到永远不达标
FUZZY_WEIGHT = 0.60          # 再降权，保证模糊命中永远排在精确命中之后
FUZZY_STRONG_MATCH = 0.78    # 已有 >= 该分数的命中时，模糊纯属噪音，不跑
FUZZY_MAX_CANDIDATES = 500   # 候选集上限，避免上万条记录各跑一次 SequenceMatcher

_WS_RE = re.compile(r"\s+")


class SearchResult(NamedTuple):
    """一次检索的完整结果，UI 直接消费。"""

    items: List[Dict[str, Any]]     # 记录字典列表（已按相关性排序）
    scores: List[float]             # 与 items 一一对应的匹配度 0..1
    query: Query                    # 规范化后的查询
    total: int                      # 命中总数（截断前）
    limited: bool                   # 是否因 max_results 被截断


def _as_text(value):
    # type: (Any) -> str
    if value is None:
        return ""
    return str(value)


def _as_list_text(value):
    # type: (Any) -> str
    """把可能为 JSON 字符串 / 列表 / 纯文本的字段拼成一段可搜索文本。"""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(_as_text(x) for x in value)
    text = _as_text(value)
    stripped = text.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        try:
            parsed = json.loads(stripped)
        except Exception:
            return text
        if isinstance(parsed, list):
            return " ".join(_as_text(x) for x in parsed)
    return text


def _lower(value):
    # type: (Any) -> str
    return _WS_RE.sub(" ", _as_text(value)).strip().lower()


class _Row(object):
    """预计算行：把每条记录一次性转成可比对的形态，查询期零转换。"""

    __slots__ = (
        "record",
        "code",
        "padded",
        "sig",
        "display_l",
        "name",
        "name_l",
        "alias_l",
        "desc_l",
        "humor_l",
        "pro_l",
        "cause_l",
        "solution_l",
    )

    def __init__(self, record):
        # type: (Dict[str, Any]) -> None
        self.record = record
        code = _as_text(record.get("stop_code") or "")
        if not code:
            # 兼容直接传原始 JSON（只有 code 字段）的调用方
            from .normalize import normalize_code

            code = normalize_code(record.get("code"))
        self.code = code
        self.padded = code[2:] if code.startswith("0X") else code
        self.sig = self.padded.lstrip("0") or "0"
        self.display_l = _lower(record.get("display_code") or code)
        self.name = _as_text(record.get("name"))
        self.name_l = _lower(record.get("name"))
        self.alias_l = _lower(_as_list_text(record.get("aliases")))
        self.desc_l = _lower(record.get("description"))
        self.humor_l = _lower(record.get("humor_desc"))
        self.pro_l = _lower(record.get("pro_desc"))
        self.cause_l = _lower(_as_list_text(record.get("causes")))
        self.solution_l = _lower(_as_list_text(record.get("solutions")))


class SearchIndex(object):
    """内存搜索索引。

    参数
    ----
    records      : 记录字典的可迭代对象（``migrate.to_record`` 的输出即可）
    cache_size   : LRU 缓存条数；0 表示禁用缓存
    max_results  : 单次返回上限（规格要求 200）
    """

    def __init__(self, records, cache_size=DEFAULT_CACHE_SIZE, max_results=MAX_RESULTS,
                 fuzzy_enabled=True):
        # type: (Iterable[Dict[str, Any]], int, int, bool) -> None
        self.rows = [_Row(record) for record in records]
        self.max_results = max(1, int(max_results))
        self.cache_size = max(0, int(cache_size))
        self.fuzzy_enabled = bool(fuzzy_enabled)
        self._cache = OrderedDict()  # type: OrderedDict

    # ------------------------------------------------------------ 统计
    def __len__(self):
        # type: () -> int
        return len(self.rows)

    @property
    def records(self):
        # type: () -> List[Dict[str, Any]]
        """全部原始记录（只读视图，供 UI 做收藏/历史筛选）。"""
        return [row.record for row in self.rows]

    def clear_cache(self):
        # type: () -> None
        self._cache.clear()

    # ------------------------------------------------------------ 检索
    def search(self, raw_query, limit=None):
        # type: (Any, Optional[int]) -> SearchResult
        """对外主入口：接受任意用户输入，永不抛异常。"""
        query = prepare(raw_query)
        return self.search_prepared(query, limit=limit)

    def search_prepared(self, query, limit=None):
        # type: (Query, Optional[int]) -> SearchResult
        """接受已规范化的 ``Query``；命中缓存的路径零计算。"""
        cap = self.max_results if limit is None else max(1, int(limit))

        if query.kind == KIND_EMPTY:
            return SearchResult([], [], query, 0, False)

        cache_key = (
            query.kind,
            query.needle,
            query.hex_raw,
            query.hex_sig,
            cap,
        )
        if self.cache_size and cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        scored = self._score_all(query)
        scored.sort(key=lambda pair: (-pair[0], pair[1].code))

        total = len(scored)
        limited = total > cap
        if limited:
            scored = scored[:cap]

        result = SearchResult(
            items=[row.record for _, row in scored],
            scores=[round(score, 4) for score, _ in scored],
            query=query,
            total=total,
            limited=limited,
        )

        if self.cache_size:
            self._cache[cache_key] = result
            if len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return result

    # ------------------------------------------------------- 内部计分
    def _score_all(self, query):
        # type: (Query) -> List[Tuple[float, _Row]]
        if query.is_hex:
            scored = self._score_hex(query)
        else:
            scored = self._score_text(query)

        if self._needs_fuzzy(query, scored):
            scored = self._merge_fuzzy(query, scored)
        return scored

    def _score_hex(self, query):
        # type: (Query) -> List[Tuple[float, _Row]]
        hex_raw = query.hex_raw
        sig = query.hex_sig
        needle = query.needle
        prefix_mode = query.hex_prefix_mode
        out = []  # type: List[Tuple[float, _Row]]

        for row in self.rows:
            score = 0.0
            if row.padded:
                if prefix_mode:
                    # 用户敲了前导零：按字面前缀比较，不能在中间插零
                    if row.padded == hex_raw:
                        score = S_CODE_EXACT
                    elif row.padded.startswith(hex_raw):
                        score = S_CODE_PREFIX
                    elif hex_raw and hex_raw in row.padded:
                        score = S_CODE_CONTAINS
                else:
                    # 蓝屏码惯例：0x7B 等价于 0x0000007B，按显著位对齐
                    if row.sig == sig:
                        score = S_CODE_EXACT
                    elif row.sig.startswith(sig):
                        score = S_CODE_PREFIX
                    elif sig and sig in row.sig:
                        score = S_CODE_CONTAINS
            if score == 0.0 and needle and needle in row.display_l:
                score = S_CODE_CONTAINS
            if score == 0.0 and needle and needle in row.name_l:
                score = S_NAME_CONTAINS
            if score > 0.0:
                out.append((score, row))
        return out

    def _score_text(self, query):
        # type: (Query) -> List[Tuple[float, _Row]]
        needle = query.needle
        tokens = [t for t in needle.split(" ") if t]
        out = []  # type: List[Tuple[float, _Row]]

        for row in self.rows:
            score = 0.0

            if row.name_l and row.name_l == needle:
                score = S_NAME_EXACT
            elif row.alias_l and needle in row.alias_l:
                # 别名精确需要整段相等；包含则稍低，但仍高于名称包含
                score = S_ALIAS_EXACT if row.alias_l == needle else S_NAME_CONTAINS + 0.04
            elif row.name_l.startswith(needle):
                score = S_NAME_CONTAINS + 0.04
            elif needle in row.name_l:
                score = S_NAME_CONTAINS
            elif needle in row.desc_l:
                score = S_DESC_CONTAINS
            elif needle in row.humor_l:
                score = S_HUMOR_CONTAINS
            elif needle in row.pro_l:
                score = S_PRO_CONTAINS
            elif needle in row.cause_l:
                score = S_CAUSE_CONTAINS
            elif needle in row.solution_l:
                score = S_SOLUTION_CONTAINS
            elif needle in row.display_l:
                score = S_CODE_CONTAINS
            elif len(tokens) > 1:
                # 多词查询：按命中词数给部分分（中文症状常见）
                hit = 0
                for token in tokens:
                    if (
                        token in row.name_l
                        or token in row.desc_l
                        or token in row.humor_l
                        or token in row.pro_l
                        or token in row.cause_l
                        or token in row.solution_l
                    ):
                        hit += 1
                if hit:
                    score = 0.30 + 0.10 * min(hit, 4)

            if score > 0.0:
                out.append((score, row))
        return out

    def _needs_fuzzy(self, query, scored):
        # type: (Query, List[Tuple[float, _Row]]) -> bool
        """只在「几乎没查到东西」时才启用模糊。

        两个必要条件，缺一不可：

        1. 命中数稀疏（< FUZZY_MIN_RESULTS）
        2. **已有命中里没有强匹配**——若已经精确/前缀命中了名字，再跑模糊
           只会把成千上万条相似名称一起捞进来，既噪音又慢。
        """
        if not self.fuzzy_enabled:
            return False
        if query.is_hex:
            return False
        if len(scored) >= FUZZY_MIN_RESULTS:
            return False
        if scored and max(score for score, _ in scored) >= FUZZY_STRONG_MATCH:
            return False
        return FUZZY_MIN_NEEDLE <= len(query.needle) <= FUZZY_MAX_NEEDLE

    def _fuzzy_candidates(self, needle):
        # type: (str) -> List[_Row]
        """缩小模糊比对范围：只取名称首字符相同的前 N 条。

        这一步把「上万条各跑一次 SequenceMatcher」压到常数级工作量的量级，
        代价是要求打错的字符串首字符仍然正确——对拼写小错的场景足够。
        """
        head = needle[0]
        out = []  # type: List[_Row]
        for row in self.rows:
            if row.name_l.startswith(head):
                out.append(row)
                if len(out) >= FUZZY_MAX_CANDIDATES:
                    break
        return out

    def _merge_fuzzy(self, query, scored):
        # type: (Query, List[Tuple[float, _Row]]) -> List[Tuple[float, _Row]]
        needle = query.needle
        known = set(id(row) for _, row in scored)
        extra = []  # type: List[Tuple[float, _Row]]

        for row in self._fuzzy_candidates(needle):
            if id(row) in known:
                continue
            by_name = SequenceMatcher(None, needle, row.name_l).ratio()
            by_code = SequenceMatcher(None, needle, row.display_l).ratio()
            raw = max(by_name, by_code)
            # 先看原始相似度：长串乘权重后容易低于任意阈值，会把正确结果误杀
            if raw >= FUZZY_RAW_THRESHOLD:
                extra.append((round(raw * FUZZY_WEIGHT, 4), row))

        return scored + extra
