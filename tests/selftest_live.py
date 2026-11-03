"""对「已经启动」的中间层做一次真实调用（模拟 matsuko_cover 插件）。

用法：
    python tests/selftest_live.py [歌曲/音频路径] [base_url]
默认使用 Applio 自带测试音频与 http://127.0.0.1:3333/。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from gradio_client import Client

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = PROJECT_DIR.parent / "ApplioV3.6.5" / "logs" / "reference" / "reference.wav"


def main() -> int:
    source = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_SOURCE)
    base_url = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:3333/"
    if not source.isdigit() and not source.lower().startswith("http") and not Path(source).exists():
        print(f"音频/歌曲不存在: {source}")
        return 1

    client = Client(base_url, verbose=False, analytics_enabled=False)
    models = client.predict(api_name="/show_model")
    print(f"模型列表({len(models)}): {models[:6]}")
    if not models:
        print("后端没有可用音色模型")
        return 1

    payload = {
        "song_name_src": source,
        "key_shift": 0,
        "vocal_vol": 0,
        "inst_vol": 0,
        "model_dropdown": models[0],
        "reverb_intensity": 4,
        "delay_intensity": 0,
        "uvr5_agg": 10,
        "uvr5_tta": False,
        "uvr5_postprocess": False,
        "uvr5_window_size": 512,
        "uvr5_high_end_process": "mirroring",
        "msst_batch_size": 2,
        "msst_num_overlap": 4,
        "msst_normalize": True,
        "vocal_postprocess": True,
        "shift_accompaniment": True,
        "f0_method": "rmvpe",
        "index_rate": 0.75,
        "filter_radius": 3,
    }

    started = time.time()
    result = client.submit(**payload, api_name="/convert").result(timeout=900)
    audio_path, cache_flag = result[0], result[1]
    size = Path(audio_path).stat().st_size / 1024
    print(f"完成：{time.time() - started:.1f}s | 缓存={cache_flag} | {size:.0f} KB | {audio_path}")
    print(f"状态：{client.predict(api_name='/status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
