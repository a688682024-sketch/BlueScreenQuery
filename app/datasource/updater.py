# -*- coding: utf-8 -*-
"""离线数据更新包：校验 → 备份 → 原子替换 → 失败回滚

更新包格式（``bluescreen-update/1``）
------------------------------------
    {
      "format": "bluescreen-update/1",
      "version": "2.1",
      "released_at": "2026-10-17",
      "checksum": "<sha256>",
      "codes": [ {"code": "0x0000007B", "name": "...", ...}, ... ]
    }

安全边界（严格按规格）
----------------------
- 格式/版本/哈希任何一项不通过 → **拒绝导入**，绝不覆盖现有数据；
- 应用前把当前库复制到 ``backups/``；
- 新库先构建到临时文件，成功后才 ``os.replace`` 落地；
- 任一步失败 → 从备份恢复并抛 ``UpdateError``，保证旧数据可用。

本模块只换「内置语料库」，不碰用户库（history/favorites/settings）。
"""

import hashlib
import json
import os
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional

from . import migrate

PACKAGE_FORMAT = "bluescreen-update/1"
MAX_RECORDS = 100000
BACKUP_KEEP = 3


class UpdateError(Exception):
    """更新失败；``str(e)`` 可直接展示给用户。"""


def _canonical(payload):
    # type: (Any) -> str
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def checksum_of(payload):
    # type: (Any) -> str
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _now_stamp():
    # type: () -> str
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def read_package(path):
    # type: (str) -> Dict[str, Any]
    """读取并完整校验更新包；任何问题都抛 ``UpdateError``。"""
    if not os.path.exists(path):
        raise UpdateError("更新包不存在：%s" % path)

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except UnicodeDecodeError:
        raise UpdateError("更新包不是 UTF-8 文本")
    except ValueError:
        raise UpdateError("更新包不是合法的 JSON")

    if not isinstance(payload, dict):
        raise UpdateError("更新包顶层必须是对象")

    fmt = payload.get("format")
    if fmt != PACKAGE_FORMAT:
        raise UpdateError("更新包格式不匹配：期望 %s，实际 %r" % (PACKAGE_FORMAT, fmt))

    version = payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise UpdateError("更新包缺少 version 字段")

    codes = payload.get("codes")
    if not isinstance(codes, list) or not codes:
        raise UpdateError("更新包 codes 为空或不是数组")
    if len(codes) > MAX_RECORDS:
        raise UpdateError("更新包记录数超过上限 %d" % MAX_RECORDS)

    expected = payload.get("checksum")
    if not isinstance(expected, str) or not expected:
        raise UpdateError("更新包缺少 checksum，无法校验完整性")

    body = dict(payload)
    body.pop("checksum", None)
    actual = checksum_of(body)
    if actual != expected:
        raise UpdateError("更新包校验和不符，文件可能被修改或损坏")

    return {
        "version": version.strip(),
        "released_at": payload.get("released_at"),
        "codes": codes,
        "count": len(codes),
        "checksum": expected,
    }


def validate_package(path):
    # type: (str) -> Dict[str, Any]
    """只校验不改动，供 UI 预览。"""
    try:
        package = read_package(path)
    except UpdateError as exc:
        return {"ok": False, "reason": str(exc), "count": 0, "version": None}

    problems = []  # type: List[str]
    for index, item in enumerate(package["codes"]):
        if not isinstance(item, dict):
            problems.append("codes[%d] 不是对象" % index)
            continue
        if not migrate.normalize_code(item.get("code")):
            problems.append("codes[%d] 缺少可用的 code" % index)
        elif not str(item.get("name") or "").strip():
            problems.append("codes[%d] 缺少 name" % index)
        if len(problems) >= 5:
            break

    if problems:
        return {
            "ok": False,
            "reason": "；".join(problems),
            "count": package["count"],
            "version": package["version"],
        }

    return {
        "ok": True,
        "reason": "",
        "count": package["count"],
        "version": package["version"],
        "released_at": package.get("released_at"),
    }


def _backup_current(db_path, backups_dir):
    # type: (str, str) -> Optional[str]
    """把当前库复制到备份目录；库不存在则返回 None。"""
    if not os.path.exists(db_path):
        return None
    if not os.path.isdir(backups_dir):
        os.makedirs(backups_dir)
    base = os.path.splitext(os.path.basename(db_path))[0]
    target = os.path.join(backups_dir, "%s.preupdate-%s.db" % (base, _now_stamp()))
    shutil.copy2(db_path, target)
    return target


def _prune(backups_dir, base, keep):
    # type: (str, str, int) -> None
    if keep <= 0 or not os.path.isdir(backups_dir):
        return
    prefix = base + ".preupdate-"
    names = sorted(
        (
            name
            for name in os.listdir(backups_dir)
            if name.startswith(prefix) and name.endswith(".db")
        ),
        reverse=True,
    )
    for name in names[keep:]:
        try:
            os.remove(os.path.join(backups_dir, name))
        except OSError:
            pass


def apply_package(package_path, db_path, schema_path, backups_dir=None, keep=BACKUP_KEEP):
    # type: (str, str, str, Optional[str], int) -> Dict[str, Any]
    """把更新包应用到内置库。

    返回 ``{"version", "count", "backup", "db_path"}``；失败抛 ``UpdateError``。
    """
    package = read_package(package_path)

    directory = os.path.dirname(os.path.abspath(db_path)) or "."
    # 目标目录可能还不存在（首次部署），必须在写暂存文件前建好
    if not os.path.isdir(directory):
        os.makedirs(directory)
    if backups_dir is None:
        backups_dir = os.path.join(directory, "backups")

    backup_path = _backup_current(db_path, backups_dir)

    # 把 codes 落到临时 JSON，复用已经过测试的 migrate.build_database
    staging = os.path.join(directory, ".update-staging.json")
    try:
        with open(staging, "w", encoding="utf-8") as handle:
            json.dump(package["codes"], handle, ensure_ascii=False)
    except Exception as exc:
        raise UpdateError("无法写入临时文件：%s" % exc)

    try:
        result = migrate.build_database(
            staging,
            db_path,
            schema_path,
            source="离线更新包",
            data_version=package["version"],
        )
    except Exception as exc:
        # 回滚：新库没有落地，旧库理论上仍在；若旧库异常则用备份恢复
        if backup_path and os.path.exists(backup_path):
            if not os.path.exists(db_path):
                try:
                    shutil.copy2(backup_path, db_path)
                except OSError:
                    pass
        raise UpdateError("应用更新失败，已保留原数据：%s" % exc)
    finally:
        if os.path.exists(staging):
            try:
                os.remove(staging)
            except OSError:
                pass

    _prune(backups_dir, os.path.splitext(os.path.basename(db_path))[0], keep)

    return {
        "version": package["version"],
        "count": result["inserted"],
        "backup": backup_path,
        "db_path": db_path,
    }


def write_package(path, codes, version, released_at=None):
    # type: (str, List[Dict[str, Any]], str, Optional[str]) -> Dict[str, Any]
    """生成一个合法更新包（供测试与"导出当前语料"使用）。"""
    body = {
        "format": PACKAGE_FORMAT,
        "version": version,
        "released_at": released_at or _now_stamp(),
        "codes": list(codes),
    }
    body["checksum"] = checksum_of(body)

    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(body, handle, ensure_ascii=False, indent=2)
    return body
