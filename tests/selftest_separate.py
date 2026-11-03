"""Standalone smoke test: UVR5 vocal separation on the Applio reference clip."""

import os
import sys
import time

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

import torch  # noqa: E402
from uvr5.vr import AudioPre  # noqa: E402

from core.paths import discover_applio_dir  # noqa: E402

APPLIO_DIR = os.environ.get("APPLIO_DIR") or str(discover_applio_dir())
# 用 Applio 自带的示例音频做测试；也可以把自己的音频路径作为第一个参数传入
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    APPLIO_DIR, "logs", "reference", "reference.wav"
)
MODEL = os.path.join(PROJECT_DIR, "models", "uvr5", "5_HP-Karaoke-UVR.pth")
OUT = os.path.join(PROJECT_DIR, "temp", "_selftest_sep")


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"torch={torch.__version__} device={device} half={device == 'cuda'}")
    t0 = time.time()
    pre = AudioPre(
        agg=10,
        model_path=MODEL,
        device=device,
        is_half=(device == "cuda"),
    )
    print(f"model loaded in {time.time() - t0:.1f}s")
    t0 = time.time()
    pre._path_audio_(SRC, OUT, OUT, "wav")
    print(f"separation took {time.time() - t0:.1f}s")
    for name in sorted(os.listdir(OUT)):
        path = os.path.join(OUT, name)
        print(f"  {name}: {os.path.getsize(path) / 1024 / 1024:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
