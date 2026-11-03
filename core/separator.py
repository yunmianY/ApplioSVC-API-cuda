"""人声/伴奏分离：封装 UVR5 VR 架构模型（等价于参考项目的 UVR5/HP5 路线）。"""

from __future__ import annotations

import contextlib
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .logging_utils import get_logger
from .paths import add_project_to_syspath
from .settings import Settings

log = get_logger("separator")

# UVR5 VR 模型官方下载页（需要手动放到 models/uvr5/ 下）
_MODEL_HELP = (
    "缺少人声分离模型。\n"
    "请把 UVR5 的 5_HP-Karaoke-UVR.pth 放到 {path}，\n"
    "或执行 python tools/download_models.py 自动下载（需要能访问 huggingface 镜像）。"
)


@dataclass
class SeparationResult:
    vocal_path: Path
    instrument_path: Path
    elapsed: float
    sample_rate: int


class VocalSeparator:
    """按 (agg, tta) 缓存 UVR5 模型实例，避免重复加载。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.RLock()
        self._instances: dict[tuple[int, bool], object] = {}
        self._torch = None

    # ------------------------------------------------------------------
    def _resolve_device(self) -> tuple[str, bool]:
        requested = str(self.settings.uvr5_device or "auto").lower()
        try:
            import torch
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"未安装 PyTorch，无法进行人声分离: {exc}") from exc
        self._torch = torch
        if requested == "cpu":
            return "cpu", False
        if requested.startswith("cuda"):
            device = requested
        else:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device.startswith("cuda") and not torch.cuda.is_available():
            log.warning("未检测到 CUDA 显卡，人声分离回退到 CPU（速度较慢）")
            return "cpu", False
        half = bool(self.settings.uvr5_half) and device.startswith("cuda")
        return device, half

    def _model_path(self) -> Path:
        path = self.settings.uvr5_model_path()
        if not path.is_file():
            raise RuntimeError(_MODEL_HELP.format(path=path))
        return path

    def _get_instance(self, agg: int, tta: bool):
        key = (int(agg), bool(tta))
        instance = self._instances.get(key)
        if instance is not None:
            return instance
        with self._lock:
            instance = self._instances.get(key)
            if instance is not None:
                return instance
            add_project_to_syspath()
            device, half = self._resolve_device()
            try:
                from uvr5.vr import AudioPre
            except Exception as exc:  # pragma: no cover
                raise RuntimeError(f"导入 UVR5 分离模块失败: {exc}") from exc
            model_path = self._model_path()
            started = time.time()
            log.info(f"加载 UVR5 分离模型 {model_path.name} (device={device}, half={half})")
            instance = AudioPre(
                agg=int(agg),
                model_path=str(model_path),
                device=device,
                is_half=half,
                tta=bool(tta),
            )
            log.info(f"分离模型加载完成，耗时 {time.time() - started:.1f}s")
            self._instances[key] = instance
            return instance

    # ------------------------------------------------------------------
    def separate(
        self,
        source_wav: Path,
        out_dir: Path,
        agg: int | None = None,
        tta: bool | None = None,
        postprocess: bool | None = None,
        window_size: int | None = None,
        high_end_process: str | None = None,
    ) -> SeparationResult:
        """把整首歌拆成人声与伴奏两条 44.1kHz 立体声 WAV。"""
        source_wav = Path(source_wav)
        if not source_wav.is_file():
            raise FileNotFoundError(f"待分离音频不存在: {source_wav}")

        agg = int(self.settings.uvr5_agg if agg is None else agg)
        tta = bool(self.settings.uvr5_tta if tta is None else tta)
        postprocess = bool(
            self.settings.uvr5_postprocess if postprocess is None else postprocess
        )
        window_size = int(self.settings.uvr5_window_size if window_size is None else window_size)
        high_end = str(
            self.settings.uvr5_high_end_process if high_end_process is None else high_end_process
        )
        if high_end not in {"mirroring", "none"}:
            high_end = "mirroring"

        pre = self._get_instance(agg, tta)
        # UVR5 的这些参数放在 data 字典里，每次推理前刷新
        pre.data.update(
            {
                "postprocess": postprocess,
                "window_size": window_size,
                "high_end_process": high_end,
                "agg": agg,
                "tta": tta,
            }
        )

        out_dir.mkdir(parents=True, exist_ok=True)
        started = time.time()
        log.info(
            f"开始分离人声：{source_wav.name} (agg={agg}, tta={tta}, "
            f"postprocess={postprocess}, window={window_size}, high_end={high_end})"
        )
        with self._lock:
            try:
                pre._path_audio_(str(source_wav), str(out_dir), str(out_dir), "wav")
            except Exception as exc:
                log.error(f"人声分离失败: {exc}")
                raise RuntimeError(f"人声分离失败: {exc}") from exc

        vocal = out_dir / f"vocal_{source_wav.name}_{agg}.wav"
        instrument = out_dir / f"instrument_{source_wav.name}_{agg}.wav"
        if not vocal.is_file() or not instrument.is_file():
            # 兜底：不同 UVR5 版本命名略有差异
            vocals = sorted(out_dir.glob("vocal_*.wav"))
            instruments = sorted(out_dir.glob("instrument_*.wav"))
            if not vocals or not instruments:
                raise RuntimeError(f"人声分离未生成预期文件（{out_dir}）")
            vocal, instrument = vocals[0], instruments[0]

        elapsed = time.time() - started
        log.info(f"分离完成：{elapsed:.1f}s -> {vocal.name} / {instrument.name}")
        return SeparationResult(
            vocal_path=vocal,
            instrument_path=instrument,
            elapsed=elapsed,
            sample_rate=44100,
        )

    def release(self) -> None:
        with self._lock:
            self._instances.clear()
        if self._torch is not None:
            with contextlib.suppress(Exception):
                self._torch.cuda.empty_cache()
        log.info("已释放分离模型与显存缓存")
