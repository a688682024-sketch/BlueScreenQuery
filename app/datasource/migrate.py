# -*- coding: utf-8 -*-
"""蓝屏代码查询器 2.0 · 数据迁移层

职责
----
把 v4 的 ``bluescreen_data.json``（``id / code / name / meaning / solution``）
无损迁移到 2.0 的 SQLite 结构，并完成两项**无损拆分**：

1. ``meaning``  -> ``description`` + ``humor_desc`` + ``pro_desc``
2. ``solution`` -> ``solutions``（步骤列表）

「无损」的可验证定义
--------------------
实际数据里的 ``meaning`` 是一段"定义 + 比喻 + 技术分析"混排的长文本，例如：

    APC（…）索引不匹配…发生了混乱。
    就像交响乐团里第二小提琴手…导致整个演奏节奏崩溃。
    从技术角度看，这通常是由于驱动程序…导致状态计数器失衡。

因此拆成**三段并按原顺序**保存，而不是硬压成两段：

    description + humor_desc + pro_desc == meaning_raw   （逐字符相等）

``solution`` 同理：

    "".join(solutions) == solution_raw                  （逐字符相等）

任何一条记录只要不满足上述等式，迁移**立即抛错并中止**，绝不静默丢字。
这是 B2 决策（不编造、不丢信息）在数据层的强制约束。

Python 3.8 约束
---------------
不使用 3.9+ 语法：无 ``list[str]`` 内置泛型、无 ``X | Y`` 联合类型、
无 ``match``。类型标注统一走 ``typing``。
"""

import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "2.0"
DEFAULT_SEVERITY = "未知"
DEFAULT_SOURCE = "内置"

# ---------------------------------------------------------------------
# 标记词表：数据驱动，便于日后扩充而不动逻辑
# ---------------------------------------------------------------------

# 比喻 / 通俗化描述的起点
HUMOR_MARKERS = (
    "这就像",
    "就像",
    "好比",
    "如同",
    "仿佛",
    "想象一下",
    "可以理解为",
    "打个比方",
)

# 技术分析的起点
PRO_MARKERS = (
    "从技术角度看",
    "从技术层面看",
    "从技术上看",
    "从技术角度",
    "技术上，",
    "技术上看",
    "技术本质",
    "技术原因",
    "技术层面",
)

# 步骤序号词（切分后保留在步骤内部）
STEP_MARKERS = (
    "首先",
    "其次",
    "再次",
    "然后",
    "接着",
    "最后",
    "此外",
    "另外",
    "再者",
    "同时",
)

_STRIP_RE = re.compile(r"[\s\-]+")
_NON_HEX_RE = re.compile(r"[^0-9A-F]")
_LINE_START_RE = re.compile(r"(?<=\n)(?=\S)")
_SENTENCE_RE = re.compile(r"[。；]")

# 单条步骤超过该字符数时，继续按句号/分号细化，避免"一条步骤 = 一整段"
MAX_STEP_CHARS = 120

_STOP_CODES_COLUMNS = (
    "stop_code",
    "display_code",
    "name",
    "aliases",
    "description",
    "humor_desc",
    "pro_desc",
    "meaning_raw",
    "causes",
    "solutions",
    "solution_raw",
    "refs",
    "severity",
    "category",
    "source",
    "data_version",
    "updated_at",
)

_INSERT_SQL = "INSERT OR REPLACE INTO stop_codes (%s) VALUES (%s)" % (
    ", ".join(_STOP_CODES_COLUMNS),
    ", ".join(["?"] * len(_STOP_CODES_COLUMNS)),
)


# =====================================================================
# 1. 代码规范化
# =====================================================================
def normalize_code(raw):
    # type: (Any) -> str
    """规范化停止代码为 2.0 主键：``0X`` + 8 位大写十六进制。

    ``0x0000007B`` / ``7b`` / ``0X7B`` / ``0000007B`` 全部得到 ``0X0000007B``。
    """
    if raw is None:
        return ""
    text = _STRIP_RE.sub("", str(raw)).upper()
    if text.startswith("0X"):
        text = text[2:]
    text = _NON_HEX_RE.sub("", text)
    if not text:
        return ""
    text = text.lstrip("0") or "0"
    return "0X" + text.zfill(8)


def to_display_code(raw):
    # type: (Any) -> str
    """展示形式：``0x0000007B``。"""
    norm = normalize_code(raw)
    if not norm:
        return ""
    return "0x" + norm[2:]


def _first_marker_index(text, markers, start=0):
    # type: (str, Sequence[str], int) -> Optional[int]
    """返回 ``markers`` 在 ``text[start:]`` 中最早出现的位置。"""
    best = None  # type: Optional[int]
    for marker in markers:
        idx = text.find(marker, start)
        if idx < 0:
            continue
        if best is None or idx < best:
            best = idx
    return best


# =====================================================================
# 2. meaning 无损拆分
# =====================================================================
def split_meaning(meaning):
    # type: (Any) -> Tuple[str, str, str]
    """把 ``meaning`` 无损拆成 ``(description, humor_desc, pro_desc)``。

    三段按原文顺序首尾相接即可逐字符还原，例如：

        description = "APC（…）索引不匹配…发生了混乱。"
        humor_desc  = "就像交响乐团…节奏崩溃。"
        pro_desc    = "从技术角度看，…状态计数器失衡。"

    - 找不到比喻标记：``humor_desc`` 为空串
    - 找不到技术标记：``pro_desc`` 为空串
    - 两者都找不到：整段原文归入 ``description``
    - 空输入：返回三个空串
    """
    raw = "" if meaning is None else str(meaning)
    if not raw.strip():
        return ("", "", "")

    humor_at = _first_marker_index(raw, HUMOR_MARKERS, 0)

    # 技术标记优先在比喻之后找；找不到再退回从头找
    pro_at = None  # type: Optional[int]
    if humor_at is not None:
        pro_at = _first_marker_index(raw, PRO_MARKERS, humor_at)
    if pro_at is None:
        pro_at = _first_marker_index(raw, PRO_MARKERS, 0)

    # 顺序纠偏：技术段必须在比喻段之后
    if humor_at is not None and pro_at is not None and pro_at < humor_at:
        pro_at = _first_marker_index(raw, PRO_MARKERS, humor_at + 1)

    if humor_at is None and pro_at is None:
        return (raw, "", "")
    if humor_at is None:
        return (raw[:pro_at], "", raw[pro_at:])
    if pro_at is None:
        return (raw[:humor_at], raw[humor_at:], "")
    return (raw[:humor_at], raw[humor_at:pro_at], raw[pro_at:])


# =====================================================================
# 3. solution 无损拆分为步骤
# =====================================================================
def _slice_by(raw, cuts):
    # type: (str, Iterable[int]) -> List[str]
    """按切点切片，保证 ``"".join(结果) == raw``；空片段自动并入相邻片段。"""
    chunks = []  # type: List[str]
    prev = 0
    for pos in sorted(set(cuts)):
        if pos <= 0 or pos >= len(raw):
            continue
        chunk = raw[prev:pos]
        if chunk:
            chunks.append(chunk)
        prev = pos
    tail = raw[prev:]
    if tail:
        chunks.append(tail)
    return chunks


def _refine_steps(chunks):
    # type: (List[str]) -> List[str]
    """把过长的步骤按句号/分号再切开；全程保持顺序与无损。"""
    refined = []  # type: List[str]
    for chunk in chunks:
        if len(chunk) > MAX_STEP_CHARS and _SENTENCE_RE.search(chunk):
            cuts = [match.end() for match in _SENTENCE_RE.finditer(chunk)]
            parts = _slice_by(chunk, cuts)
            if len(parts) > 1 and "".join(parts) == chunk:
                refined.extend(parts)
                continue
        refined.append(chunk)
    return refined


def split_steps(solution):
    # type: (Any) -> List[str]
    """把 ``solution`` 拆成步骤列表，``"".join(结果) == 原文``。

    三级切分策略，逐级退化，全程无损：

    1. **序号词**（首先/其次/最后/此外…）——语义最准确，序号词保留在步骤开头；
    2. **换行**后紧接非空白字符的位置——覆盖 ``1. xxx`` 这类手工编号；
    3. **句号 / 分号**——当前两级都切不动时（整段散文），按句子边界切分，
       否则一条几百字的排查说明会被压成单条步骤，失去「步骤列表」的意义。

    不做任何 ``strip``——去掉空白会破坏无损性；显示层需要时自行处理。
    """
    raw = "" if solution is None else str(solution)
    if not raw.strip():
        return []

    cuts = set()  # type: set

    # ① 序号词切分（跳过位置 0，避免产生空的首段）
    for marker in STEP_MARKERS:
        idx = raw.find(marker, 1)
        while idx >= 0:
            cuts.add(idx)
            idx = raw.find(marker, idx + len(marker))

    # ② 行首切分
    for match in _LINE_START_RE.finditer(raw):
        pos = match.start()
        if pos > 0:
            cuts.add(pos)

    chunks = _slice_by(raw, cuts)

    # ③ 退化：前两级没切开（或只切出 1 条）时，按句子边界重切
    if len(chunks) < 2:
        sentence_cuts = set(
            match.end() for match in _SENTENCE_RE.finditer(raw)
        )
        if sentence_cuts:
            chunks = _slice_by(raw, sentence_cuts)

    # ④ 细化：仍然过长的片段继续按句切开，保证步骤可读
    chunks = _refine_steps(chunks)

    # 兜底：切片理论上必然无损，此处仅防御编程错误
    if "".join(chunks) != raw:
        return [raw]
    return chunks or [raw]


# =====================================================================
# 4. 记录构建
# =====================================================================
def _json_text_or_none(value):
    # type: (Any) -> Optional[str]
    """把列表类字段序列化为 JSON 文本；缺失/空值统一为 ``None``（不编造）。"""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        items = [str(x).strip() for x in value if str(x).strip()]
        if not items:
            return None
        return json.dumps(items, ensure_ascii=False)
    text = str(value).strip()
    return text or None


def to_record(item, source=DEFAULT_SOURCE, data_version=SCHEMA_VERSION, updated_at=None):
    # type: (Dict[str, Any], str, str, Optional[str]) -> Dict[str, Any]
    """把一条原始 JSON 记录转成 2.0 的行字典，并强制校验无损性。"""
    if not isinstance(item, dict):
        raise TypeError("记录必须是 dict，实际收到 %r" % (type(item).__name__,))

    stop_code = normalize_code(item.get("code"))
    if not stop_code:
        raise ValueError("记录缺少可用 code：%r" % (item.get("code"),))

    name = str(item.get("name") or "").strip()
    if not name:
        raise ValueError("记录 %s 缺少 name" % stop_code)

    meaning_raw = "" if item.get("meaning") is None else str(item.get("meaning"))
    description, humor_desc, pro_desc = split_meaning(meaning_raw)
    if description + humor_desc + pro_desc != meaning_raw:
        raise ValueError("meaning 无损拆分失败：%s" % stop_code)

    solution_raw = "" if item.get("solution") is None else str(item.get("solution"))
    steps = split_steps(solution_raw)
    if "".join(steps) != solution_raw:
        raise ValueError("solution 无损拆分失败：%s" % stop_code)

    return {
        "stop_code": stop_code,
        "display_code": to_display_code(item.get("code")),
        "name": name,
        # v4 数据无此三项 —— 一律 None，UI 显示「暂无信息」
        "aliases": _json_text_or_none(item.get("aliases")),
        "description": description,
        "humor_desc": humor_desc,
        "pro_desc": pro_desc,
        "meaning_raw": meaning_raw,
        "causes": _json_text_or_none(item.get("causes")),
        "solutions": json.dumps(steps, ensure_ascii=False),
        "solution_raw": solution_raw,
        "refs": _json_text_or_none(item.get("refs")),
        "severity": str(item.get("severity") or DEFAULT_SEVERITY),
        "category": (str(item.get("category")).strip() if item.get("category") else None),
        "source": source,
        "data_version": data_version,
        "updated_at": updated_at or _now_iso(),
    }


def _now_iso():
    # type: () -> str
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


# =====================================================================
# 5. 读取与建库
# =====================================================================
def load_json(path):
    # type: (str) -> List[Dict[str, Any]]
    """读取 bluescreen_data.json；同时兼容顶层数组与 ``{"data": [...]}``。"""
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        payload = payload.get("data") or []
    if not isinstance(payload, list):
        raise ValueError("数据文件顶层必须是数组或 {'data': [...]}")
    return payload


def iter_records(items, source=DEFAULT_SOURCE, data_version=SCHEMA_VERSION):
    # type: (Iterable[Dict[str, Any]], str, str) -> Iterable[Dict[str, Any]]
    """逐条转换；用于流式调用与单元测试。"""
    stamp = _now_iso()
    for item in items:
        yield to_record(item, source=source, data_version=data_version, updated_at=stamp)


def dedupe_records(records):
    # type: (Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]
    """按 ``stop_code`` 去重，返回 (保留列表, 被丢弃的重复码列表)。"""
    kept = []  # type: List[Dict[str, Any]]
    dropped = []  # type: List[str]
    seen = set()  # type: set
    for record in records:
        key = record["stop_code"]
        if key in seen:
            dropped.append(key)
            continue
        seen.add(key)
        kept.append(record)
    return kept, dropped


def build_database(json_path, db_path, schema_path, source=DEFAULT_SOURCE, data_version=SCHEMA_VERSION):
    # type: (str, str, str, str, str) -> Dict[str, Any]
    """从 JSON 构建只读 SQLite 库。

    流程：读取 -> 逐条转换（含无损校验）-> 去重 -> 写入临时库 -> 原子替换。
    任何一步失败都不会留下半成品：临时文件在异常时被清除。
    """
    items = load_json(json_path)
    records, dropped = dedupe_records(iter_records(items, source=source, data_version=data_version))

    with open(schema_path, "r", encoding="utf-8") as handle:
        schema_sql = handle.read()

    target_dir = os.path.dirname(os.path.abspath(db_path))
    if target_dir and not os.path.isdir(target_dir):
        os.makedirs(target_dir)

    tmp_path = db_path + ".tmp"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    connection = None
    try:
        connection = sqlite3.connect(tmp_path)
        connection.executescript(schema_sql)
        rows = [tuple(record[column] for column in _STOP_CODES_COLUMNS) for record in records]
        connection.executemany(_INSERT_SQL, rows)
        connection.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )
        connection.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("data_version", data_version),
        )
        connection.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("source", source),
        )
        connection.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("imported_at", _now_iso()),
        )
        connection.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("record_count", str(len(records))),
        )
        connection.commit()
    except Exception:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
            connection = None
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    os.replace(tmp_path, db_path)

    return {
        "db_path": db_path,
        "total": len(items),
        "inserted": len(records),
        "dropped": dropped,
        "data_version": data_version,
        "source": source,
    }


# =====================================================================
# 6. 命令行入口（手动重建内置库时使用）
# =====================================================================
def main(argv=None):
    # type: (Optional[Sequence[str]]) -> int
    import argparse

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser = argparse.ArgumentParser(description="把 bluescreen_data.json 迁移为 2.0 的 SQLite 内置库")
    parser.add_argument("--json", default=os.path.join(root, "bluescreen_data.json"))
    parser.add_argument("--db", default=os.path.join(root, "data", "bluescreen.db"))
    parser.add_argument("--schema", default=os.path.join(root, "data", "schema.sql"))
    args = parser.parse_args(argv)

    result = build_database(args.json, args.db, args.schema)
    print("内置库已生成: %s" % result["db_path"])
    print("源记录数: %d  写入: %d  重复丢弃: %d" % (result["total"], result["inserted"], len(result["dropped"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
