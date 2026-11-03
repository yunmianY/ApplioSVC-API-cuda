"""下载链路自测：验证「登录态接口 → 公共接口」的回退逻辑。

用法： python tests/selftest_download.py [歌曲ID]
不配置 netease_api_base 时会走公共源（免费歌应能下到）。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from core import downloader  # noqa: E402
from core.settings import get_settings  # noqa: E402

SONG_ID = sys.argv[1] if len(sys.argv) > 1 else "2629004781"


def try_download(label: str, api_base: str, cookie: str) -> bool:
    settings = get_settings()
    settings.netease_api_base = api_base
    settings.netease_cookie = cookie
    work = Path(tempfile.mkdtemp(prefix="appliosvc_dl_"))
    try:
        path = downloader._download_netease(SONG_ID, settings, work)
    except Exception as exc:
        print(f"[{label}] 失败: {str(exc)[:200]}")
        return False
    size = path.stat().st_size / 1024 / 1024
    print(f"[{label}] 成功: {size:.1f} MB -> {path.name}")
    path.unlink(missing_ok=True)
    return True


def main() -> int:
    ok = 0
    # 1) 纯公共源
    if try_download("公共源", "", ""):
        ok += 1
    # 2) 配置了不存在的本地 API + 无 cookie → 应告警并回退
    if try_download("API不可达/无cookie", "http://127.0.0.1:39999", ""):
        ok += 1
    # 3) 配置了不存在的本地 API + 假 cookie → 应回退
    if try_download("API不可达/假cookie", "http://127.0.0.1:39999", "MUSIC_U=fake_for_test"):
        ok += 1
    print(f"\n{ok}/3 条链路可用（预期 3/3，说明回退正常）")
    return 0 if ok == 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
