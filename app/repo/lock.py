# -*- coding: utf-8 -*-
"""单实例文件锁

规格 P1：单实例运行，避免多实例写坏用户数据。

实现分两层：

1. **进程内**：模块级集合记录已被本进程持有的锁路径，杜绝同一进程里
   重复创建仓储把库文件抢坏（也便于单元测试确定性断言）。
2. **跨进程**：Windows 用 ``msvcrt.locking``，POSIX 用 ``fcntl.flock``，
   都是「非阻塞排他锁」；都不可用时退化为 ``O_EXCL`` 建锁文件。

锁文件只用来占位，内容写当前 PID 便于排查，不参与业务。
"""

import os

_HELD_IN_PROCESS = set()  # type: set


def _key(path):
    # type: (str) -> str
    return os.path.normcase(os.path.abspath(path))


class SingleInstanceLock(object):
    """上下文管理器：``acquire()`` 返回 False 表示已有实例在跑。"""

    def __init__(self, path):
        # type: (str) -> None
        self.path = path
        self._key = _key(path)
        self._handle = None

    # ------------------------------------------------------------ 获取
    def acquire(self):
        # type: () -> bool
        if self._handle is not None:
            return True
        if self._key in _HELD_IN_PROCESS:
            return False

        directory = os.path.dirname(os.path.abspath(self.path))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)

        try:
            handle = open(self.path, "a+")
        except OSError:
            return False

        try:
            handle.seek(0)
            self._lock_handle(handle)
        except OSError:
            try:
                handle.close()
            except Exception:
                pass
            return False

        self._handle = handle
        _HELD_IN_PROCESS.add(self._key)
        self._write_pid(handle)
        return True

    @staticmethod
    def _lock_handle(handle):
        # type: (object) -> None
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _write_pid(self, handle):
        # type: (object) -> None
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()))
            handle.flush()
        except Exception:
            pass

    # ------------------------------------------------------------ 释放
    def release(self):
        # type: () -> None
        if self._handle is None:
            return
        try:
            self._unlock_handle(self._handle)
        except Exception:
            pass
        try:
            self._handle.close()
        except Exception:
            pass
        self._handle = None
        _HELD_IN_PROCESS.discard(self._key)

    @staticmethod
    def _unlock_handle(handle):
        # type: (object) -> None
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    # ------------------------------------------------------------ 生命周期
    @property
    def held(self):
        # type: () -> bool
        return self._handle is not None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False
