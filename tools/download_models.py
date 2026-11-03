"""下载中间层所需的模型权重（人声分离 UVR5 模型）。

用法：
    python tools/download_models.py            # 缺什么下什么
    python tools/download_models.py --check    # 只检查
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from core.paths import DEFAULT_UVR5_MODEL, ensure_runtime_dirs  # noqa: E402

# 国内可直连的 HuggingFace 镜像；官方源在部分网络下不可达，放最后
UVR5_MODEL_SOURCES = [
    os.environ.get("APPLIOSVC_UVR5_URL", ""),
    "https://hf-mirror.com/QQSong/UVR5/resolve/main/5_HP-Karaoke-UVR.pth",
    "https://huggingface.co/QQSong/UVR5/resolve/main/5_HP-Karaoke-UVR.pth",
]
MIN_EXPECTED_BYTES = 50 * 1024 * 1024


def _download(url: str, target: Path) -> None:
    print(f"下载 {url}")
    request = Request(url, headers={"User-Agent": "ApplioSVC-API/1.0"})
    with urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".part")
        downloaded = 0
        started = time.time()
        with temp.open("wb") as stream:
            while True:
                chunk = response.read(1024 * 512)
                if not chunk:
                    break
                stream.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 / total
                    speed = downloaded / 1024 / 1024 / max(time.time() - started, 0.001)
                    print(f"\r  {pct:5.1f}%  {downloaded / 1024 / 1024:6.1f} MB  ({speed:.1f} MB/s)", end="")
        print()
        temp.replace(target)


def ensure_uvr5_model(check_only: bool = False) -> bool:
    target = DEFAULT_UVR5_MODEL
    if target.is_file() and target.stat().st_size >= MIN_EXPECTED_BYTES:
        print(f"[OK] 已存在分离模型: {target} ({target.stat().st_size / 1024 / 1024:.1f} MB)")
        return True
    if check_only:
        print(f"[缺失] 分离模型: {target}")
        return False

    errors: list[str] = []
    for url in UVR5_MODEL_SOURCES:
        if not url:
            continue
        try:
            _download(url, target)
            if target.stat().st_size < MIN_EXPECTED_BYTES:
                raise RuntimeError(f"文件过小（{target.stat().st_size} 字节），疑似不是模型")
            print(f"[OK] 已保存: {target} ({target.stat().st_size / 1024 / 1024:.1f} MB)")
            return True
        except Exception as exc:  # 逐个源重试
            errors.append(f"{url} -> {exc}")
            target.unlink(missing_ok=True)
    print("[失败] 所有下载源都不可用：")
    for line in errors:
        print("  -", line)
    print(
        "\n可以手动下载 UVR5 的 5_HP-Karaoke-UVR.pth，"
        f"放到：{target}"
    )
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 ApplioSVC-API 所需模型")
    parser.add_argument("--check", action="store_true", help="只检查本地模型是否齐全")
    args = parser.parse_args()
    ensure_runtime_dirs()
    return 0 if ensure_uvr5_model(args.check) else 1


if __name__ == "__main__":
    raise SystemExit(main())
