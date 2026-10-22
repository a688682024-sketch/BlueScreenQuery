# -*- coding: utf-8 -*-
"""收藏导出 / 导入

导出格式（``bluescreen-favorites/1``）
------------------------------------
    {
      "format": "bluescreen-favorites/1",
      "version": "2.0",
      "exported_at": "2026-10-17 19:00:00",
      "count": 3,
      "codes": ["0X0000007B", "0X0000000A", "0X00000133"],
      "checksum": "<sha256(除 checksum 外的规范化 JSON)>"
    }

三条安全约束
------------
1. **哈希校验**：导入前重算并比对，任何改动都会被发现。
2. **格式校验**：字段缺失、类型不对、代码无法规范化 → 拒绝并说明原因，
   绝不部分导入。
3. **原子写**：导出先写 ``.tmp`` 再 ``os.replace``，中途失败不留半个文件。

导入模式
--------
- ``merge``   ：并集（默认，最安全）
- ``replace`` ：先用导入内容替换本地收藏，**必须由调用方二次确认**
"""

import hashlib
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .search.normalize import normalize_code

FAVORITES_FORMAT = "bluescreen-favorites/1"
APP_SCHEMA_VERSION = "2.0"
MAX_ITEMS = 5000


class TransferError(Exception):
    """导入/导出失败；``str(e)`` 是可直接展示给用户的中文原因。"""


def _now():
    # type: () -> str
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _canonical(payload):
    # type: (Any) -> str
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def checksum_of(payload):
    # type: (Any) -> str
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def build_export(codes, exported_at=None):
    # type: (Sequence[Any], Optional[str]) -> Dict[str, Any]
    """把代码序列整理成导出载荷（已排序去重）。"""
    normalized = []  # type: List[str]
    seen = set()
    for raw in codes or []:
        code = normalize_code(raw)
        if code and code not in seen:
            seen.add(code)
            normalized.append(code)
    normalized.sort()

    body = {
        "format": FAVORITES_FORMAT,
        "version": APP_SCHEMA_VERSION,
        "exported_at": exported_at or _now(),
        "count": len(normalized),
        "codes": normalized,
    }
    body["checksum"] = checksum_of(body)
    return body


def export_favorites(repo, path):
    # type: (Any, str) -> Dict[str, Any]
    """把仓储里的收藏写到 ``path``（原子替换）。返回统计信息。"""
    codes = list(repo.favorite_codes())
    payload = build_export(codes)

    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)

    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception as exc:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise TransferError("导出失败：%s" % exc)

    return {"path": path, "count": payload["count"]}


def read_package(path):
    # type: (str) -> Dict[str, Any]
    """读取并校验收藏包；失败抛 ``TransferError``（中文原因）。"""
    if not os.path.exists(path):
        raise TransferError("文件不存在：%s" % path)

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except UnicodeDecodeError:
        raise TransferError("文件不是 UTF-8 文本，可能选错了文件")
    except ValueError:
        raise TransferError("文件不是合法的 JSON")

    if not isinstance(payload, dict):
        raise TransferError("收藏包顶层必须是对象")

    fmt = payload.get("format")
    if fmt != FAVORITES_FORMAT:
        raise TransferError(
            "格式不匹配：期望 %s，实际 %r" % (FAVORITES_FORMAT, fmt)
        )

    codes = payload.get("codes")
    if not isinstance(codes, list):
        raise TransferError("codes 字段缺失或不是数组")
    if len(codes) > MAX_ITEMS:
        raise TransferError("条目数超过上限 %d" % MAX_ITEMS)

    normalized = []  # type: List[str]
    seen = set()
    for index, raw in enumerate(codes):
        if not isinstance(raw, str):
            raise TransferError("codes[%d] 不是字符串" % index)
        code = normalize_code(raw)
        if not code:
            raise TransferError("codes[%d] 不是合法的停止代码：%r" % (index, raw))
        if code not in seen:
            seen.add(code)
            normalized.append(code)

    expected = payload.get("checksum")
    if not isinstance(expected, str) or not expected:
        raise TransferError("缺少 checksum，无法校验完整性")

    body = dict(payload)
    body.pop("checksum", None)
    actual = checksum_of(body)
    if actual != expected:
        raise TransferError("校验和不符，文件可能被修改或损坏")

    declared_count = payload.get("count")
    if declared_count is not None and declared_count != len(codes):
        raise TransferError(
            "count 字段（%r）与实际条目数（%d）不一致"
            % (declared_count, len(codes))
        )

    return {
        "format": fmt,
        "version": payload.get("version"),
        "exported_at": payload.get("exported_at"),
        "codes": sorted(normalized),
        "count": len(normalized),
    }


def import_favorites(repo, path, mode="merge"):
    # type: (Any, str, str) -> Dict[str, Any]
    """导入收藏。``mode`` 为 ``merge`` 或 ``replace``。"""
    if mode not in ("merge", "replace"):
        raise TransferError("未知导入模式：%r" % (mode,))

    package = read_package(path)
    incoming = package["codes"]

    before = set(repo.favorite_codes())
    if mode == "replace":
        for code in before:
            repo.remove_favorite(code)

    added = 0
    for code in incoming:
        if repo.add_favorite(code):
            added += 1

    after = set(repo.favorite_codes())
    return {
        "mode": mode,
        "incoming": len(incoming),
        "added": added,
        "removed": len(before - after),
        "total": len(after),
    }
