# -*- coding: utf-8 -*-
"""蓝屏代码查询器 2.0 启动入口

直接运行：
    python main.py

打包后用 PyInstaller --windowed --onefile 生成单文件 exe。
"""

import os
import sys

# 高 DPI 相关：必须在创建 QApplication 之前设置
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)


def main(argv=None):
    # type: (object) -> int
    from app.ui.features import AppFeatures

    features = AppFeatures()

    # 老系统（Win7/8）关闭动效，避免自绘半透明窗口闪烁
    if not features.animations:
        os.environ.setdefault("QT_QUICK_BACKEND", "software")

    from app.ui.main_window import create_app

    app, window = create_app(sys.argv if argv is None else argv)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
