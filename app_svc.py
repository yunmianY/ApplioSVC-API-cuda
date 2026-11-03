"""SVC 兼容中间层入口（端口 9999）。

对应 AstrBot 插件 matsuko_cover 的 svc_base_url。
注意：本实现是「用 Applio 模型回放 SVC 参数契约」，并非 SVC-Fusion 上游，
音色列表同样是 Applio 的 .pth 模型；如需真正的 SVC-Fusion，请使用 SVCVC-API-SVF。
"""

from __future__ import annotations

import sys

from app_common import main

if __name__ == "__main__":
    raise SystemExit(main("svc", sys.argv[1:]))
