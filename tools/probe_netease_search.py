"""用 gdstudio 搜索接口找几首可播放的歌，再验证下载源是否真的能拿到音频。"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import requests  # noqa: E402

from core.settings import get_settings  # noqa: E402

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://music.163.com/",
}


def main() -> int:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "童话"
    search = requests.get(
        "https://music-api.gdstudio.xyz/api.php",
        params={"types": "search", "source": "netease", "name": keyword, "count": 5, "pages": 1},
        headers=HEADERS,
        timeout=20,
    ).json()
    if not isinstance(search, list) or not search:
        print(f"搜索无结果: {search}")
        return 1

    settings = get_settings()
    for song in search[:5]:
        song_id = song.get("id")
        name = f"{song.get('name')} - {song.get('artist')}"
        for template in settings.download_sources:
            url = template.format(song_id=song_id)
            try:
                response = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
                ctype = (response.headers.get("Content-Type") or "").lower()
                if "json" in ctype or response.text[:1].lstrip() in {"{", "["}:
                    from core.downloader import _extract_audio_url

                    audio_url = _extract_audio_url(response.json())
                    if not audio_url:
                        continue
                    head = requests.get(audio_url, headers=HEADERS, timeout=20, stream=True)
                    chunk = next(head.iter_content(65536), b"")
                    if head.status_code == 200 and len(chunk) > 40000:
                        print(f"[OK] {name} (id={song_id}) via {url}\n     audio={audio_url[:120]} ({len(chunk)}+ B)")
                        return 0
                elif "audio" in ctype and len(response.content) > 100000:
                    print(f"[OK] {name} (id={song_id}) direct audio via {url} ({len(response.content)} B)")
                    return 0
            except Exception as exc:
                print(f"  [x] {name} id={song_id} {url} -> {exc}")
        print(f"[x] {name} (id={song_id}) 所有源都失败")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
