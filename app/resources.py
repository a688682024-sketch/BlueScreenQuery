# -*- coding: utf-8 -*-
"""外部资源与配置解析

设计目标
--------
让「打包后的 exe 旁边可以有可编辑的配置文件」，同时**绝不因此启动失败**：

    读资源 → 先找 exe 同目录的外部文件 → 找不到再用打包进 exe 的内置副本
    外部文件存在但内容非法 → 记录原因，回退内置默认值，继续启动

也就是说：``config\\`` 目录可以整块删掉，程序功能不受任何影响，
只是回到出厂默认参数。

路径约定
--------
- 源码运行：外部目录 = 项目根目录
- 打包运行：外部目录 = exe 所在目录；内置副本在 PyInstaller 的 ``_MEIPASS``
"""

import json
import os
import sys
from typing import Any, Dict, Optional, Tuple

CONFIG_DIR = "config"

_log: list = []


def _note(message):
    # type: (str) -> None
    """记录配置加载过程中的异常（不抛给用户，供诊断使用）。"""
    _log.append(str(message))
    try:
        del _log[:-50]
    except Exception:
        pass


def diagnostics():
    # type: () -> list
    """返回最近的配置加载异常列表。"""
    return list(_log)


def project_root():
    # type: () -> str
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_frozen():
    # type: () -> bool
    return bool(getattr(sys, "frozen", False))


def external_dir():
    # type: () -> str
    """用户可写/可改的目录：打包后是 exe 所在目录。"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return project_root()


def bundled_dir():
    # type: () -> str
    """只读内置副本目录：打包后是 _MEIPASS，源码运行时等于项目根。"""
    return getattr(sys, "_MEIPASS", None) or project_root()


def external_path(*parts):
    # type: (str) -> str
    return os.path.join(external_dir(), *parts)


def bundled_path(*parts):
    # type: (str) -> str
    return os.path.join(bundled_dir(), *parts)


def find_asset(relative):
    # type: (str) -> Optional[str]
    """按「外部优先、内置兜底」查找资源；都不存在返回 None。"""
    for base in (external_dir(), bundled_dir()):
        candidate = os.path.join(base, relative)
        if os.path.exists(candidate):
            return candidate
    return None


def config_path(name):
    # type: (str) -> Optional[str]
    """``config/<name>.json`` 的实际路径（外部优先）。"""
    return find_asset(os.path.join(CONFIG_DIR, name + ".json"))


def load_config(name, defaults=None):
    # type: (str, Optional[Dict[str, Any]]) -> Dict[str, Any]
    """读取一份配置；任何异常都退回默认值，绝不抛错。"""
    result = dict(defaults or {})
    path = config_path(name)
    if path is None:
        return result

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except UnicodeDecodeError:
        _note("%s 不是 UTF-8 文本，已使用默认配置" % path)
        return result
    except ValueError as exc:
        _note("%s 不是合法 JSON（%s），已使用默认配置" % (path, exc))
        return result
    except OSError as exc:
        _note("%s 读取失败（%s），已使用默认配置" % (path, exc))
        return result

    if not isinstance(payload, dict):
        _note("%s 顶层不是对象，已使用默认配置" % path)
        return result

    for key, value in payload.items():
        if str(key).startswith("_"):
            continue  # 下划线开头是说明字段，忽略
        result[key] = value
    return result


# ---------------------------------------------------------------------
# 取值助手：外部配置里的类型是用户手写的，必须逐个校验
# ---------------------------------------------------------------------
def as_int(value, default, minimum=None, maximum=None):
    # type: (Any, int, Optional[int], Optional[int]) -> int
    try:
        number = int(value)
    except (TypeError, ValueError):
        return int(default)
    if minimum is not None and number < minimum:
        return int(default)
    if maximum is not None and number > maximum:
        return int(default)
    return number


def as_bool(value, default):
    # type: (Any, bool) -> bool
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off", ""):
            return False
    return bool(default)


def as_text(value, default):
    # type: (Any, str) -> str
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def as_theme(value, default="dark"):
    # type: (Any, str) -> str
    text = as_text(value, default)
    return text if text in ("dark", "light") else default


def as_nested_int(container, key, default, minimum=None, maximum=None):
    # type: (Any, str, int, Optional[int], Optional[int]) -> int
    if not isinstance(container, dict):
        return int(default)
    return as_int(container.get(key), default, minimum, maximum)

def user_data_root():
    # type: () -> str
    """用户数据根目录（与用户库 user.db 同级）。"""
    try:
        from .repo.paths import ensure_dir, user_data_dir

        return ensure_dir(user_data_dir())
    except Exception:
        pass

    if os.name == "nt":
        base = (
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or os.path.expanduser("~")
        )
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "share"
        )
    root = os.path.join(base, "BlueScreenQuery")
    try:
        if not os.path.isdir(root):
            os.makedirs(root)
    except OSError:
        pass
    return root


def runtime_db_path():
    # type: () -> str
    """可写的内置语料库路径：打包后用用户数据目录，源码运行用项目 data/。"""
    if is_frozen():
        return os.path.join(user_data_root(), "bluescreen.db")
    return os.path.join(project_root(), "data", "bluescreen.db")


def ensure_runtime_db():
    # type: () -> Optional[str]
    """冻结态首次运行时，把打包进 exe 的内置库复制到可写目录。"""
    target = runtime_db_path()
    if os.path.exists(target):
        return target

    source = find_asset(os.path.join("data", "bluescreen.db"))
    if not source:
        return None
    if os.path.abspath(source) == os.path.abspath(target):
        return target

    try:
        import shutil

        directory = os.path.dirname(target)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        shutil.copy2(source, target)
        return target
    except OSError as exc:
        _note("初始化可写数据库失败：%s" % exc)
        return None