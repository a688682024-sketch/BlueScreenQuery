# -*- coding: utf-8 -*-
"""用户数据路径解析

规格要求「用 platformdirs 获取用户数据目录，禁止硬编码路径」。
这里以 platformdirs 为主，同时保留一条纯环境变量的退化路径，
使项目在没装该依赖时也能启动（不因缺依赖而白屏）。
"""

import os

APP_NAME = "BlueScreenQuery"
APP_AUTHOR = "BlueScreenQuery"


def user_data_dir():
    # type: () -> str
    """返回用户数据目录（不保证已存在）。"""
    try:
        import platformdirs

        return platformdirs.user_data_dir(APP_NAME, APP_AUTHOR)
    except Exception:
        pass

    # 退化：仍然只读环境变量，不写死盘符
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return os.path.join(base, APP_NAME)
    else:
        base = os.environ.get("XDG_DATA_HOME")
        if not base:
            home = os.environ.get("HOME") or os.path.expanduser("~")
            base = os.path.join(home, ".local", "share")
        return os.path.join(base, APP_NAME)

    return os.path.join(os.path.expanduser("~"), "." + APP_NAME.lower())


def ensure_dir(path):
    # type: (str) -> str
    if path and not os.path.isdir(path):
        os.makedirs(path)
    return path


def user_db_path():
    # type: () -> str
    return os.path.join(ensure_dir(user_data_dir()), "user.db")


def backups_dir():
    # type: () -> str
    return ensure_dir(os.path.join(user_data_dir(), "backups"))


def lock_path():
    # type: () -> str
    return os.path.join(ensure_dir(user_data_dir()), "instance.lock")
