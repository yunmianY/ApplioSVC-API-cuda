"""探测网易云下载源是否可用（只测网络，不保存音频）。"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import requests  # noqa: E402

from core.settings import get_settings  # noqa: E402

SONG_ID = sys.argv[1] if len(sys.argv) > 1 else "186016"


def main() -> int:
    settings = get_settings()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://music.163.com/",
    }
    ok = 0
    for template in settings.download_sources:
        url = template.format(song_id=SONG_ID)
        try:
            response = requests.get(url, headers=headers, timeout=20, allow_redirects=True, stream=True)
            chunk = next(response.iter_content(65536), b"")
            ctype = response.headers.get("Content-Type")
            looks_audio = "audio" in str(ctype) or len(chunk) > 50000
            print(
                f"[{'OK  ' if response.status_code == 200 and looks_audio else 'WARN'}] "
                f"HTTP {response.status_code} type={ctype} first={len(chunk)}B {url}"
            )
            if response.status_code == 200 and looks_audio:
                ok += 1
        except Exception as exc:
            print(f"[FAIL] {url} -> {exc}")
    print(f"\n可用下载源: {ok}/{len(settings.download_sources)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
