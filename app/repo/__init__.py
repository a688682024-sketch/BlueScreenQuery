# -*- coding: utf-8 -*-
"""用户数据层公开接口。"""

from .lock import SingleInstanceLock
from .paths import (
    APP_NAME,
    backups_dir,
    ensure_dir,
    lock_path,
    user_data_dir,
    user_db_path,
)
from .userdb import (
    BACKUP_KEEP,
    HISTORY_LIMIT,
    SCHEMA_VERSION,
    UserRepository,
)

__all__ = [
    "APP_NAME",
    "BACKUP_KEEP",
    "HISTORY_LIMIT",
    "SCHEMA_VERSION",
    "SingleInstanceLock",
    "UserRepository",
    "backups_dir",
    "ensure_dir",
    "lock_path",
    "user_data_dir",
    "user_db_path",
]
