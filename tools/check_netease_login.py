"""检查网易云登录态（VIP 下载用）。

用法：
    python tools/check_netease_login.py            # 用 config.json 里的配置
    python tools/check_netease_login.py 186016     # 指定要试的歌曲 ID

前提：本机已运行 NeteaseCloudMusicApi（默认 http://127.0.0.1:3000），
并且把登录后的 MUSIC_U 填进了 config.json 的 netease_cookie。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import requests  # noqa: E402

from core.downloader import normalize_cookie  # noqa: E402
from core.settings import get_settings  # noqa: E402

TEST_SONG_ID = sys.argv[1] if len(sys.argv) > 1 else "186016"


def mask(secret: str) -> str:
    if not secret:
        return "(空)"
    if len(secret) <= 10:
        return secret[:2] + "***"
    return f"{secret[:6]}...{secret[-4:]}（长度 {len(secret)}）"


def main() -> int:
    settings = get_settings()
    base = (settings.netease_api_base or "").strip().rstrip("/")
    raw_cookie = settings.netease_cookie or ""
    cookie = normalize_cookie(raw_cookie)
    if raw_cookie and cookie != raw_cookie.strip():
        print(f"（已自动清洗 cookie：{len(raw_cookie)} 字符 -> {len(cookie)} 字符）")

    print(f"netease_api_base : {base or '(未配置)'}")
    print(f"netease_cookie   : {mask(cookie)}")
    print(f"netease_level    : {settings.netease_level}")
    if not base:
        print("\n[提示] 还没配置自建 API。先运行： npx NeteaseCloudMusicApi@4.32.0")
        print("       然后把地址填进 config.json 的 netease_api_base")
        return 1
    if not cookie:
        print("\n[提示] 没有 cookie，VIP 歌曲下不了。先登录拿到 MUSIC_U 再填入 netease_cookie")
        return 1

    headers = {"Cookie": cookie, "User-Agent": "Mozilla/5.0"}

    print("\n=== /login/status ===")
    try:
        response = requests.get(f"{base}/login/status", headers=headers, timeout=10)
        data = response.json()
        account = (data.get("data") or {}).get("account") or {}
        profile = (data.get("data") or {}).get("profile") or {}
        if account:
            print(f"已登录账号: {profile.get('nickname', '?')} (uid={account.get('id')})")
            print(f"VIP 类型  : {profile.get('vipType')}（0=无，11=黑胶，其他见网易云文档）")
        else:
            print(f"未登录或 cookie 已失效: {json.dumps(data, ensure_ascii=False)[:300]}")
            return 1
    except Exception as exc:
        print(f"请求失败（服务没起？）: {exc}")
        return 1

    print(f"\n=== /song/url/v1 取地址（测试歌曲 {TEST_SONG_ID}）===")
    try:
        response = requests.get(
            f"{base}/song/url/v1",
            params={"id": TEST_SONG_ID, "level": settings.netease_level},
            headers=headers,
            timeout=15,
        )
        payload = response.json()
        items = payload.get("data") or []
        url = items[0].get("url") if items else None
        if url:
            print(f"拿到播放地址: {url[:110]}...")
            codec = (items[0].get("type") or items[0].get("encodeType") or "?")
            size = items[0].get("size") or 0
            print(f"格式={codec} 大小={size / 1024 / 1024:.1f} MB")
            print("\n结论：登录态有效，VIP 歌曲可以由中间层直接下载。")
            return 0
        print(f"没拿到地址（该歌可能需要更高 VIP / 无版权）: {json.dumps(payload, ensure_ascii=False)[:300]}")
        return 1
    except Exception as exc:
        print(f"请求失败: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
