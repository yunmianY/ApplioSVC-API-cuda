"""环境自检：一次性打印中间层能否跑起来的关键信息。

用法： python tools/check_env.py
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))


def _line(name: str, ok: bool, detail: str = "") -> None:
    flag = "OK  " if ok else "FAIL"
    print(f"[{flag}] {name:<22} {detail}")


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def main() -> int:
    print(f"Python: {sys.version.split()[0]}  ({sys.executable})")
    print(f"项目目录: {PROJECT_DIR}\n")

    failures = 0

    try:
        import torch

        cuda = bool(torch.cuda.is_available())
        _line("PyTorch", True, torch.__version__)
        _line(
            "CUDA",
            cuda,
            torch.cuda.get_device_name(0) if cuda else "未检测到 CUDA 显卡",
        )
        if not cuda:
            failures += 1
    except Exception as exc:
        _line("PyTorch", False, str(exc))
        failures += 1

    for module in ("gradio", "librosa", "soundfile", "pydub", "pedalboard", "faiss"):
        try:
            mod = __import__(module)
            _line(module, True, getattr(mod, "__version__", ""))
        except Exception as exc:
            _line(module, False, str(exc))
            failures += 1

    from core.paths import DEFAULT_UVR5_MODEL, discover_applio_dir, find_ffmpeg

    try:
        applio = discover_applio_dir()
        _line("Applio 目录", True, str(applio))
    except Exception as exc:
        _line("Applio 目录", False, str(exc))
        applio = None
        failures += 1

    ffmpeg = find_ffmpeg(applio)
    _line("ffmpeg", bool(ffmpeg), ffmpeg or "未找到（MP3 导出会失败）")
    if not ffmpeg:
        failures += 1

    _line(
        "UVR5 分离模型",
        DEFAULT_UVR5_MODEL.is_file(),
        f"{DEFAULT_UVR5_MODEL} ({DEFAULT_UVR5_MODEL.stat().st_size / 1024 / 1024:.1f} MB)"
        if DEFAULT_UVR5_MODEL.is_file()
        else f"缺失: {DEFAULT_UVR5_MODEL}",
    )
    if not DEFAULT_UVR5_MODEL.is_file():
        failures += 1

    try:
        from core.settings import get_settings

        settings = get_settings()
        models = []
        for root in settings.model_roots():
            models.extend(root.rglob("*.pth"))
        usable = [p for p in models if "pretraineds" not in str(p).lower()]
        _line("音色模型 .pth", bool(usable), f"{len(usable)} 个（扫描 {settings.model_dirs}）")
        if not usable:
            failures += 1

        for port in (settings.rvc_port, settings.svc_port):
            _line(f"端口 {port}", port_free(port), "可用" if port_free(port) else "已被占用")
    except Exception as exc:
        _line("配置加载", False, str(exc))
        failures += 1

    print()
    if failures:
        print(f"有 {failures} 项需要处理，请按上面的 FAIL 提示修复。")
    else:
        print("全部检查通过，可以启动中间层了。")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
