# -*- coding: utf-8 -*-
"""用户数据仓储层：历史 / 收藏 / 设置 / 元信息

设计约定
--------
- **分库**：用户库与内置语料库物理分离，语料只读，删掉用户库不影响查询。
- **单事务**：每个写操作包在一个事务里，要么全成要么全不成。
- **原子文件**：备份与导出走「写临时文件 + ``os.replace``」，不留半成品。
- **损坏自愈**：打开时跑 ``PRAGMA integrity_check``，失败就把旧库改名为
  ``*.corrupt-<时间戳>`` 留证，再重建空库，绝不让程序起不来。
- **幂等**：重复收藏、重复历史、删除不存在的记录都不抛异常。
- **历史裁剪**：按 ``normalized_query`` 去重，只保留最近 N 条（默认 50）。
"""

import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..search.normalize import normalize_code

HISTORY_LIMIT = 50
BACKUP_KEEP = 3
SCHEMA_VERSION = "1"

_FALLBACK_NORMALIZE = lambda text: " ".join(str(text).lower().split())

_DEFAULT_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_schema.sql")


def _now():
    # type: () -> str
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _decode_value(text, default):
    # type: (Any, Any) -> Any
    if text is None:
        return default
    try:
        return json.loads(text)
    except Exception:
        return text


def _read_schema(path):
    # type: (str) -> str
    if not os.path.exists(path):
        raise FileNotFoundError(
            "缺少用户库表结构文件 user_schema.sql：%s" % path
        )
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


class UserRepository(object):
    """用户数据读写入口。线程内安全，跨进程请配合 ``SingleInstanceLock``。"""

    def __init__(self, db_path, schema_path=None, history_limit=HISTORY_LIMIT, backup_keep=BACKUP_KEEP):
        # type: (str, Optional[str], int, int) -> None
        self.db_path = db_path
        self.history_limit = max(1, int(history_limit))
        self.backup_keep = max(0, int(backup_keep))
        self.recovered = False
        self._lock = threading.RLock()
        self._schema_sql = _read_schema(schema_path or _DEFAULT_SCHEMA_PATH)
        self._conn = None  # type: Optional[sqlite3.Connection]
        self._open()

    # ================================================================ 生命周期
    def _open(self):
        # type: () -> None
        directory = os.path.dirname(os.path.abspath(self.db_path))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)

        connection = self._connect()
        if not self._is_healthy(connection):
            try:
                connection.close()
            except Exception:
                pass
            self._quarantine()
            self.recovered = True
            connection = self._connect()

        connection.executescript(self._schema_sql)
        connection.execute(
            "INSERT OR IGNORE INTO schema_info (version) VALUES (?)", (SCHEMA_VERSION,)
        )
        connection.commit()
        self._conn = connection

    def _connect(self):
        # type: () -> sqlite3.Connection
        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _is_healthy(connection):
        # type: (sqlite3.Connection) -> bool
        try:
            row = connection.execute("PRAGMA integrity_check").fetchone()
            return bool(row) and str(row[0]).lower() == "ok"
        except sqlite3.DatabaseError:
            return False
        except Exception:
            return False

    def _quarantine(self):
        # type: () -> Optional[str]
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = "%s.corrupt-%s" % (self.db_path, stamp)
        try:
            os.replace(self.db_path, target)
        except OSError:
            return None
        for suffix in ("-wal", "-shm"):
            side = self.db_path + suffix
            if os.path.exists(side):
                try:
                    os.remove(side)
                except OSError:
                    pass
        return target

    def close(self):
        # type: () -> None
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    @property
    def connection(self):
        # type: () -> sqlite3.Connection
        if self._conn is None:
            raise RuntimeError("用户库已关闭")
        return self._conn

    # ================================================================ 历史
    def add_history(self, raw_query, normalized_query=None, stop_code=None, created_at=None):
        # type: (Any, Optional[str], Optional[str], Optional[str]) -> Optional[int]
        """记录一次查询。空查询不记录；同一 normalized_query 只留最新一条。"""
        raw = "" if raw_query is None else str(raw_query).strip()
        if not raw:
            return None

        normalized = normalized_query
        if not normalized:
            normalized = _FALLBACK_NORMALIZE(raw)
        normalized = str(normalized).strip()
        if not normalized:
            return None

        stamp = created_at or _now()
        with self._lock, self.connection:
            self.connection.execute(
                "DELETE FROM history WHERE normalized_query = ?", (normalized,)
            )
            cursor = self.connection.execute(
                "INSERT INTO history (raw_query, normalized_query, stop_code, created_at) "
                "VALUES (?, ?, ?, ?)",
                (raw, normalized, stop_code, stamp),
            )
            row_id = cursor.lastrowid
            self._trim_history()
        return row_id

    def _trim_history(self):
        # type: () -> None
        self.connection.execute(
            "DELETE FROM history WHERE id NOT IN "
            "(SELECT id FROM history ORDER BY id DESC LIMIT ?)",
            (self.history_limit,),
        )

    def list_history(self, limit=None):
        # type: (Optional[int]) -> List[Dict[str, Any]]
        cap = self.history_limit if limit is None else max(1, int(limit))
        rows = self.connection.execute(
            "SELECT id, raw_query, normalized_query, stop_code, created_at "
            "FROM history ORDER BY id DESC LIMIT ?",
            (cap,),
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_history(self, history_id):
        # type: (Any) -> bool
        """删除单条历史；不存在时返回 False（不抛异常）。"""
        try:
            target = int(history_id)
        except (TypeError, ValueError):
            return False
        with self._lock, self.connection:
            cursor = self.connection.execute("DELETE FROM history WHERE id = ?", (target,))
        return cursor.rowcount > 0

    def clear_history(self):
        # type: () -> int
        """清空历史，返回删除条数。"""
        with self._lock, self.connection:
            cursor = self.connection.execute("DELETE FROM history")
        return max(0, cursor.rowcount or 0)

    def history_count(self):
        # type: () -> int
        row = self.connection.execute("SELECT COUNT(*) AS n FROM history").fetchone()
        return int(row["n"]) if row else 0

    # ================================================================ 收藏
    def add_favorite(self, stop_code, created_at=None):
        # type: (Any, Optional[str]) -> bool
        """收藏；已存在返回 False（幂等）。"""
        code = normalize_code(stop_code)
        if not code:
            return False
        with self._lock, self.connection:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO favorites (stop_code, created_at) VALUES (?, ?)",
                (code, created_at or _now()),
            )
        return cursor.rowcount > 0

    def remove_favorite(self, stop_code):
        # type: (Any) -> bool
        code = normalize_code(stop_code)
        if not code:
            return False
        with self._lock, self.connection:
            cursor = self.connection.execute(
                "DELETE FROM favorites WHERE stop_code = ?", (code,)
            )
        return cursor.rowcount > 0

    def toggle_favorite(self, stop_code):
        # type: (Any) -> bool
        """切换收藏状态，返回切换后的状态。"""
        code = normalize_code(stop_code)
        if not code:
            return False
        with self._lock, self.connection:
            hit = self.connection.execute(
                "SELECT 1 FROM favorites WHERE stop_code = ?", (code,)
            ).fetchone()
            if hit:
                self.connection.execute(
                    "DELETE FROM favorites WHERE stop_code = ?", (code,)
                )
                return False
            self.connection.execute(
                "INSERT OR IGNORE INTO favorites (stop_code, created_at) VALUES (?, ?)",
                (code, _now()),
            )
            return True

    def is_favorite(self, stop_code):
        # type: (Any) -> bool
        code = normalize_code(stop_code)
        if not code:
            return False
        return (
            self.connection.execute(
                "SELECT 1 FROM favorites WHERE stop_code = ?", (code,)
            ).fetchone()
            is not None
        )

    def list_favorites(self):
        # type: () -> List[Dict[str, Any]]
        rows = self.connection.execute(
            "SELECT stop_code, created_at FROM favorites ORDER BY created_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def favorite_codes(self):
        # type: () -> List[str]
        return [row["stop_code"] for row in self.list_favorites()]

    def favorite_count(self):
        # type: () -> int
        row = self.connection.execute("SELECT COUNT(*) AS n FROM favorites").fetchone()
        return int(row["n"]) if row else 0

    # ================================================================ 设置
    def set_setting(self, key, value):
        # type: (Any, Any) -> None
        name = str(key or "").strip()
        if not name:
            raise ValueError("setting key 不能为空")
        payload = json.dumps(value, ensure_ascii=False)
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                (name, payload, _now()),
            )

    def get_setting(self, key, default=None):
        # type: (Any, Any) -> Any
        row = self.connection.execute(
            "SELECT value FROM settings WHERE key = ?", (str(key),)
        ).fetchone()
        if row is None:
            return default
        return _decode_value(row["value"], default)

    def get_settings(self):
        # type: () -> Dict[str, Any]
        result = {}  # type: Dict[str, Any]
        for row in self.connection.execute("SELECT key, value FROM settings"):
            result[row["key"]] = _decode_value(row["value"], None)
        return result

    def delete_setting(self, key):
        # type: (Any) -> bool
        with self._lock, self.connection:
            cursor = self.connection.execute(
                "DELETE FROM settings WHERE key = ?", (str(key),)
            )
        return cursor.rowcount > 0

    # ================================================================ 元信息
    def set_meta(self, key, value):
        # type: (Any, Any) -> None
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO data_meta (key, value) VALUES (?, ?)",
                (str(key), "" if value is None else str(value)),
            )

    def get_meta(self, key, default=None):
        # type: (Any, Any) -> Any
        row = self.connection.execute(
            "SELECT value FROM data_meta WHERE key = ?", (str(key),)
        ).fetchone()
        return default if row is None else row["value"]

    # ================================================================ 备份
    def backup(self, keep=None):
        # type: (Optional[int]) -> Optional[str]
        """用 SQLite 在线备份 API 生成一致快照，再原子改名落地。

        走临时文件 + ``os.replace``，即使中途失败也不会留下半个"可用"备份。
        """
        limit = self.backup_keep if keep is None else max(0, int(keep))
        directory = os.path.join(
            os.path.dirname(os.path.abspath(self.db_path)), "backups"
        )
        if not os.path.isdir(directory):
            os.makedirs(directory)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        base = os.path.splitext(os.path.basename(self.db_path))[0]
        target = os.path.join(directory, "%s.bak-%s.db" % (base, stamp))
        tmp_path = target + ".tmp"

        with self._lock:
            self.connection.commit()
            destination = sqlite3.connect(tmp_path)
            try:
                self.connection.backup(destination)
            finally:
                destination.close()

        try:
            os.replace(tmp_path, target)
        except OSError:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            return None

        if limit > 0:
            self._prune_backups(directory, base, limit)
        return target

    @staticmethod
    def _prune_backups(directory, base, keep):
        # type: (str, str, int) -> List[str]
        prefix = base + ".bak-"
        candidates = []
        for name in os.listdir(directory):
            if name.startswith(prefix) and name.endswith(".db"):
                candidates.append(name)
        candidates.sort(reverse=True)  # 时间戳前缀，倒序即最新在前
        removed = []
        for name in candidates[keep:]:
            try:
                os.remove(os.path.join(directory, name))
                removed.append(name)
            except OSError:
                pass
        return removed

    def list_backups(self):
        # type: () -> List[str]
        directory = os.path.join(
            os.path.dirname(os.path.abspath(self.db_path)), "backups"
        )
        if not os.path.isdir(directory):
            return []
        base = os.path.splitext(os.path.basename(self.db_path))[0]
        names = [
            os.path.join(directory, name)
            for name in os.listdir(directory)
            if name.startswith(base + ".bak-") and name.endswith(".db")
        ]
        names.sort(reverse=True)
        return names
