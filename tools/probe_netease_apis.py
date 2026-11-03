"""探测若干公共网易云解析接口，找出当前网络下真正可用的下载源。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import requests  # noqa: E402

SONG_ID = sys.argv[1] if len(sys.argv) > 1 else "186016"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://music.163.com/",
}

CANDIDATES = [
    ("hhlqilongzhu", f"https://www.hhlqilongzhu.cn/api/dg_wyymusic.php?id={SONG_ID}&br=7&type=json"),
    ("injahow", f"https://api.injahow.cn/meting/?type=url&id={SONG_ID}"),
    ("qijieya", f"https://api.qijieya.cn/meting/?type=url&id={SONG_ID}"),
    ("gdstudio", f"https://music-api.gdstudio.xyz/api.php?types=url&source=netease&id={SONG_ID}&br=320"),
    ("vkeys", f"https://api.vkeys.cn/v2/music/netease?id={SONG_ID}"),
    ("kxzjoker", f"https://api.kxzjoker.cn/api/163_music?url=https://music.163.com/song?id={SONG_ID}&level=standard&type=json"),
]


def find_url(payload) -> str | None:
    if isinstance(payload, str):
        return payload if payload.startswith("http") else None
    if isinstance(payload, dict):
        for key in ("music_url", "url", "data", "song_url", "src"):
            if key in payload:
                found = find_url(payload[key])
                if found:
                    return found
        for value in payload.values():
            found = find_url(value)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = find_url(item)
            if found:
                return found
    return None


def main() -> int:
    usable = []
    for name, url in CANDIDATES:
        try:
            response = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
            body = response.text[:300]
            audio_url = None
            if response.headers.get("Content-Type", "").startswith("application/json") or body.lstrip().startswith("{"):
                try:
                    audio_url = find_url(response.json())
                except json.JSONDecodeError:
                    audio_url = None
            elif response.status_code == 200 and len(response.content) > 50000:
                audio_url = url

            status = "?"
            size = 0
            if audio_url:
                try:
                    head = requests.get(
                        audio_url, headers=HEADERS, timeout=20, stream=True, allow_redirects=True
                    )
                    chunk = next(head.iter_content(65536), b"")
                    size = len(chunk)
                    status = f"HTTP {head.status_code} {head.headers.get('Content-Type')} {size}B"
                    if head.status_code == 200 and size > 40000:
                        usable.append((name, audio_url))
                except Exception as exc:
                    status = f"音频下载失败: {exc}"
            print(f"[{name}] resp={response.status_code} audio={audio_url!r}\n    probe={status}\n    body={body[:160]!r}")
        except Exception as exc:
            print(f"[{name}] 请求失败: {exc}")

    print("\n可用源:", [name for name, _ in usable] or "无")
    return 0 if usable else 1


if __name__ == "__main__":
    raise SystemExit(main())
