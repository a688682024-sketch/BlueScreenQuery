# -*- coding: utf-8 -*-
"""平台能力与全局特性开关（AppFeatures）

为什么需要它
------------
v4 在 Win7 上出现闪烁/黑屏：自绘半透明窗口 + 持续动画在无 DWM 合成
的老系统上会不断整窗重绘。2.0 用一个统一开关把「动效」集中管控：

  Win10 及以上（build >= 10240）  -> 启用全部平滑动画
  Win8/8.1、Win7（build < 10240） -> 关闭动画，直接静态渲染，防闪烁
  非 Windows                      -> 默认启用（Qt 在 X11/macOS 下表现正常）

同时修正 v4 的一处缺陷：``platform.release()`` 在 Win11 上恒返回 "10"
（内核主版本仍是 10.0），从 build 号判断才可靠。
"""

import os
import sys

# Windows build 分界线
BUILD_WINDOWS_10 = 10240
BUILD_WINDOWS_8_1 = 9600
BUILD_WINDOWS_8 = 9200
BUILD_WINDOWS_7 = 7600
BUILD_WINDOWS_11 = 22000

# 动画时长（毫秒）；关闭动效时统一为 0
DURATION_FAST = 167
DURATION_NORMAL = 250
DURATION_TOAST = 1600


def windows_build():
    # type: () -> int
    """返回 Windows build 号；非 Windows 或读取失败返回 0。"""
    if sys.platform != "win32":
        return 0
    try:
        return int(sys.getwindowsversion().build)  # type: ignore[attr-defined]
    except Exception:
        return 0


def os_label(build=None):
    # type: (object) -> str
    """按 build 号给出系统名称；不再依赖不可靠的 ``platform.release()``。"""
    if build is None:
        build = windows_build()
    try:
        build = int(build)
    except (TypeError, ValueError):
        build = 0

    if sys.platform != "win32":
        return sys.platform
    if build >= BUILD_WINDOWS_11:
        return "Windows 11"
    if build >= BUILD_WINDOWS_10:
        return "Windows 10"
    if build >= BUILD_WINDOWS_8_1:
        return "Windows 8.1"
    if build >= BUILD_WINDOWS_8:
        return "Windows 8"
    if build >= BUILD_WINDOWS_7:
        return "Windows 7"
    return "Windows"


def pointer_bits():
    # type: () -> int
    """当前 Python 解释器的位数（不是操作系统位数）。"""
    import struct

    return struct.calcsize("P") * 8


def os_architecture():
    # type: () -> str
    """操作系统位数：优先读 PROCESSOR_ARCHITECTURE，避免把 32 位 Python
    跑在 64 位系统上误报成 32 位。"""
    arch = os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get(
        "PROCESSOR_ARCHITECTURE"
    )
    if arch:
        upper = arch.upper()
        if "64" in upper:
            return "64位"
        if "86" in upper or "32" in upper:
            return "32位"
    return "64位" if pointer_bits() == 64 else "32位"


class AppFeatures(object):
    """全局特性开关。UI 层只读它，不再各自探测平台。"""

    def __init__(self, force_animations=None, probe_build=None):
        # type: (object, object) -> None
        self.is_windows = sys.platform == "win32"
        self.build = windows_build() if probe_build is None else int(probe_build or 0)
        self.os_name = os_label(self.build)
        self.arch = os_architecture()
        self.pointer_bits = pointer_bits()

        self.animations, self.animation_reason = self._decide(force_animations)

        # 动效关闭时把时长压到 0，所有动画代码会自动退化为瞬时完成
        self.duration_fast = DURATION_FAST if self.animations else 0
        self.duration_normal = DURATION_NORMAL if self.animations else 0
        self.toast_duration = DURATION_TOAST if self.animations else 900

    def _decide(self, force):
        # type: (object) -> tuple
        if force is not None:
            enabled = bool(force)
            return enabled, "调用方强制%s" % ("启用" if enabled else "禁用")
        if not self.is_windows:
            return True, "非 Windows 平台，默认启用"
        if self.build >= BUILD_WINDOWS_10:
            return True, "%s（build %d）支持合成，启用动效" % (self.os_name, self.build)
        return False, "%s（build %d）无可靠合成，关闭动效防闪烁" % (
            self.os_name,
            self.build,
        )

    # ------------------------------------------------------------ 便捷属性
    @property
    def system_label(self):
        # type: () -> str
        """底部状态栏用的一行系统信息。"""
        return "%s · %s" % (self.os_name, self.arch)

    def __repr__(self):
        return "<AppFeatures %s animations=%s (%s)>" % (
            self.os_name,
            self.animations,
            self.animation_reason,
        )
