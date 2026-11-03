"""RVC 兼容中间层入口（端口 3333）。

对应 AstrBot 插件 matsuko_cover 的 rvc_base_url。
"""

from __future__ import annotations

import sys

from app_common import main

if __name__ == "__main__":
    raise SystemExit(main("rvc", sys.argv[1:]))
