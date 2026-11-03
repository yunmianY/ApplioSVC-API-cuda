"""接口契约自测：用 gradio_client 完全模拟 AstrBot 插件的调用方式。

验证点：
1. /convert 的形参名与 matsuko_cover 插件提交的关键字参数一一对应；
2. /show_model 返回模型名列表；
3. 通过 **kwargs 提交后能拿到音频文件路径 + 缓存标记。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from gradio_client import Client  # noqa: E402

from app_common import _bootstrap, build_ui  # noqa: E402

PORT = 3399
SOURCE = PROJECT_DIR.parent / "ApplioV3.6.5" / "logs" / "reference" / "reference.wav"

PLUGIN_KWARGS = {
    "song_name_src": str(SOURCE),
    "key_shift": 0,
    "vocal_vol": 0,
    "inst_vol": 0,
    "model_dropdown": "",  # 运行时填
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


def main() -> int:
    settings, pipeline = _bootstrap("rvc")
    app = build_ui("rvc", settings, pipeline)
    app.queue(max_size=8, api_open=True, default_concurrency_limit=1)
    app.launch(
        server_name="127.0.0.1",
        server_port=PORT,
        prevent_thread_lock=True,
        quiet=True,
        show_error=True,
        allowed_paths=[str(PROJECT_DIR / "temp"), str(PROJECT_DIR / "output")],
    )
    time.sleep(2)
    try:
        client = Client(f"http://127.0.0.1:{PORT}/", verbose=False, analytics_enabled=False)
        print("=== API ===")
        client.view_api(print_info=True)

        endpoints = client.endpoints
        values = endpoints.values() if isinstance(endpoints, dict) else endpoints
        names = sorted({
            "/" + str(getattr(e, "api_name", "")).lstrip("/")
            for e in values
            if isinstance(getattr(e, "api_name", None), str)
        })
        print(f"endpoints={names}")

        models = client.predict(api_name="/show_model")
        print(f"models({len(models)})={models[:5]}")
        assert isinstance(models, list) and models, "show_model 应返回非空列表"

        print(f"clear_cache={client.predict('all', api_name='/clear_cache')}")

        PLUGIN_KWARGS["model_dropdown"] = models[0]
        started = time.time()
        job = client.submit(**PLUGIN_KWARGS, api_name="/convert")
        result = job.result(timeout=900)
        print(f"convert 耗时 {time.time() - started:.1f}s -> {result!r}")
        assert isinstance(result, (list, tuple)) and len(result) >= 2, f"返回结构异常: {result!r}"
        audio_path, cache_flag = result[0], result[1]
        assert Path(audio_path).is_file() and Path(audio_path).stat().st_size > 0, "音频文件无效"
        assert str(cache_flag).lower() == "false", "首次运行不应命中缓存"
        print(f"audio={audio_path} ({Path(audio_path).stat().st_size / 1024:.0f} KB) flag={cache_flag}")

        # 再跑一次同样的参数，应命中缓存
        job2 = client.submit(**PLUGIN_KWARGS, api_name="/convert")
        result2 = job2.result(timeout=300)
        print(f"第二次 -> flag={result2[1]}")
        assert str(result2[1]).lower() == "true", "第二次应返回缓存命中标记"

        info = client.predict(api_name="/cache_info")
        print(f"cache_info={info}")
        print("OK")
        return 0
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main())
