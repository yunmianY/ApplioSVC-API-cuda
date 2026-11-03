"""校验 SVC(9999) 网关的 /convert 参数名与插件提交的关键字一致。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from gradio_client import Client  # noqa: E402

from app_common import _bootstrap, build_ui  # noqa: E402

PORT = 3398

# matsuko_cover 在 svc 分支里提交的关键字参数
EXPECTED = {
    "song_name_src",
    "key_shift",
    "vocal_vol",
    "inst_vol",
    "model_dropdown",
    "reverb_intensity",
    "delay_intensity",
    "uvr5_agg",
    "uvr5_tta",
    "uvr5_postprocess",
    "uvr5_window_size",
    "uvr5_high_end_process",
    "msst_batch_size",
    "msst_num_overlap",
    "msst_normalize",
    "vocal_postprocess",
    "shift_accompaniment",
    "svc_f0_method",
}


def parameter_names(client: Client, api_name: str) -> set[str]:
    endpoints = client.endpoints
    values = endpoints.values() if isinstance(endpoints, dict) else endpoints
    for endpoint in values:
        if "/" + str(getattr(endpoint, "api_name", "")).lstrip("/") != api_name:
            continue
        info = getattr(endpoint, "parameters_info", None) or []
        return {item["parameter_name"] for item in info}
    return set()


def main() -> int:
    settings, pipeline = _bootstrap("svc")
    app = build_ui("svc", settings, pipeline)
    app.queue(max_size=4, api_open=True, default_concurrency_limit=1)
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
        names = parameter_names(client, "/convert")
        print(f"svc /convert 参数({len(names)}): {sorted(names)}")
        missing = EXPECTED - names
        extra = names - EXPECTED
        print(f"缺少: {sorted(missing) or '无'} | 多余: {sorted(extra) or '无'}")
        assert not missing, f"插件会提交但这些参数不存在: {missing}"
        models = client.predict(api_name="/show_model")
        print(f"svc 模型列表: {models}")
        print("OK")
        return 0
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main())
