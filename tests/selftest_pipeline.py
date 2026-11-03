"""端到端自测（不经过 Gradio）：本地音频 → 分离 → Applio → 混音。"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from core.logging_utils import setup_logging  # noqa: E402
from core.paths import find_ffmpeg  # noqa: E402
from core.pipeline import ConvertParams, CoverPipeline  # noqa: E402
from core.settings import get_settings  # noqa: E402

SOURCE = PROJECT_DIR.parent / "ApplioV3.6.5" / "logs" / "reference" / "reference.wav"


def main() -> int:
    setup_logging("INFO", filename="selftest.log")
    settings = get_settings()
    settings.ffmpeg_path = find_ffmpeg(settings.applio_path) or ""
    print(f"applio={settings.applio_path}")
    print(f"ffmpeg={settings.ffmpeg_path}")

    pipeline = CoverPipeline(settings)
    pipeline.engine.activate()
    models = pipeline.refresh_models()
    print(f"models={models[:5]} ... 共 {len(models)}")
    if not models:
        print("没有可用模型，先跑一次 Applio 训练或把 .pth 放进 logs/")
        return 1

    model_name = next((m for m in models if "Feiyu" in m), models[0])
    params = ConvertParams(
        song=str(SOURCE),
        model_name=model_name,
        key_shift=2,
        vocal_vol=0,
        inst_vol=0,
        reverb_intensity=4,
        delay_intensity=0,
        f0_method="rmvpe",
        index_rate=0.75,
        uvr5_agg=10,
        vocal_postprocess=True,
        shift_accompaniment=True,
    )

    started = time.time()
    outcome = pipeline.convert(params, progress=lambda v, desc=None: None)
    print(f"第一次：{outcome.elapsed:.1f}s cache_hit={outcome.cache_hit} -> {outcome.output_path}")
    print(f"阶段耗时: {outcome.stage_timings}")
    assert outcome.output_path.is_file() and outcome.output_path.stat().st_size > 0

    started = time.time()
    again = pipeline.convert(params, progress=lambda v, desc=None: None)
    print(f"第二次：cache_hit={again.cache_hit} 耗时 {time.time() - started:.2f}s")
    assert again.cache_hit, "相同参数第二次应命中缓存"

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
