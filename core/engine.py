"""Applio 推理引擎封装：进程内复用 VoiceConverter，避免每次重新加载模型。"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .logging_utils import describe_device, get_logger
from .models import VoiceModel, ascii_safe_audio_path
from .settings import Settings

log = get_logger("engine")

# 插件/上游可能传 RVC 的 f0 名称，Applio 只支持下面 4 种
F0_ALIASES = {
    "rmvpe": "rmvpe",
    "rmvpe_gpu": "rmvpe",
    "fcpe": "fcpe",
    "crepe": "crepe",
    "crepe-tiny": "crepe-tiny",
    "crepe_tiny": "crepe-tiny",
    # Applio 没有实现 harvest / pm，退回到最稳的 rmvpe
    "harvest": "rmvpe",
    "pm": "rmvpe",
}
F0_CHOICES = ["rmvpe", "fcpe", "crepe", "crepe-tiny"]


def normalize_f0_method(method: str | None, default: str = "rmvpe") -> str:
    key = str(method or default).strip().lower()
    resolved = F0_ALIASES.get(key)
    if resolved is None:
        log.warning(f"未知的音高提取算法 {method!r}，回退到 {default}")
        return F0_ALIASES.get(default, "rmvpe")
    if resolved != key:
        log.info(f"音高提取算法 {method!r} 已映射为 Applio 的 {resolved!r}")
    return resolved


@dataclass
class ConvertResult:
    output_path: Path
    elapsed: float
    model_loaded: bool
    sample_rate: int


class ApplioEngine:
    """单例式的 Applio 推理后端。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.RLock()
        self._converter = None
        self._loaded_model: str | None = None
        self._torch = None
        self._activated = False

    # ------------------------------------------------------------------
    def activate(self) -> None:
        """把工作目录切到 Applio（其内部大量使用相对路径），并准备 sys.path。"""
        if self._activated:
            return
        applio = self.settings.applio_path
        if not applio.is_dir():
            raise RuntimeError(f"Applio 目录不存在: {applio}")
        if str(applio) not in sys.path:
            sys.path.insert(0, str(applio))
        os.chdir(applio)
        self._activated = True
        log.info(f"Applio 工作目录: {applio}")

    def _ensure_converter(self):
        with self._lock:
            if self._converter is not None:
                return self._converter
            self.activate()
            try:
                import torch  # noqa: F401
                from rvc.infer.infer import VoiceConverter
            except Exception as exc:  # pragma: no cover - 依赖缺失时给出明确提示
                raise RuntimeError(
                    "导入 Applio 推理模块失败，请确认中间层使用 Applio 的 env\\python.exe 启动，"
                    f"且 Applio 目录完整。原始错误: {exc}"
                ) from exc
            self._torch = torch
            log.info(f"推理设备: {describe_device(torch)}")
            self._converter = VoiceConverter()
            return self._converter

    # ------------------------------------------------------------------
    def convert(
        self,
        input_path: Path,
        output_path: Path,
        model: VoiceModel,
        pitch: int = 0,
        f0_method: str = "rmvpe",
        index_rate: float = 0.75,
        protect: float | None = None,
        volume_envelope: float | None = None,
        split_audio: bool = False,
        clean_audio: bool = False,
    ) -> ConvertResult:
        """执行一次音色转换。"""
        if not input_path.is_file():
            raise FileNotFoundError(f"待转换音频不存在: {input_path}")

        f0 = normalize_f0_method(f0_method, self.settings.default_f0_method)
        protect = float(self.settings.protect if protect is None else protect)
        volume_envelope = float(
            self.settings.volume_envelope if volume_envelope is None else volume_envelope
        )
        index_rate = max(0.0, min(1.0, float(index_rate)))

        index_path = ""
        if model.index_path and index_rate > 0:
            index_path = str(ascii_safe_audio_path(model.index_path))

        with self._lock:
            converter = self._ensure_converter()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            already_loaded = self._loaded_model == str(model.pth_path)
            started = time.time()
            log.info(
                f"开始推理：model={model.name} pitch={pitch:+d} f0={f0} "
                f"index_rate={index_rate:.2f} index={'有' if index_path else '无'} "
                f"{'(复用已加载模型)' if already_loaded else '(加载模型)'}"
            )
            try:
                converter.convert_audio(
                    audio_input_path=str(input_path),
                    audio_output_path=str(output_path),
                    model_path=str(model.pth_path),
                    index_path=index_path,
                    pitch=int(pitch),
                    f0_method=f0,
                    index_rate=index_rate,
                    volume_envelope=volume_envelope,
                    protect=protect,
                    hop_length=128,
                    split_audio=bool(split_audio),
                    f0_autotune=False,
                    embedder_model="contentvec",
                    embedder_model_custom=None,
                    clean_audio=bool(clean_audio),
                    clean_strength=0.5,
                    export_format="WAV",
                )
            except Exception as exc:
                log.error(f"推理失败: {exc}")
                raise RuntimeError(f"Applio 推理失败: {exc}") from exc
            finally:
                # VoiceConverter 自己会记录当前加载的模型，这里同步一份供状态展示
                self._loaded_model = (
                    str(converter.loaded_model) if converter.loaded_model else None
                )

            if not output_path.is_file():
                raise RuntimeError(f"推理未生成输出文件: {output_path}")

            elapsed = time.time() - started
            sample_rate = int(getattr(converter, "tgt_sr", 0) or 0)
            log.info(f"推理完成：{elapsed:.1f}s，采样率 {sample_rate}，输出 {output_path.name}")
            return ConvertResult(
                output_path=output_path,
                elapsed=elapsed,
                model_loaded=not already_loaded,
                sample_rate=sample_rate,
            )

    # ------------------------------------------------------------------
    def unload(self) -> None:
        """释放模型，便于切换音色或排查显存问题。"""
        with self._lock:
            if self._converter is None:
                return
            with contextlib.suppress(Exception):
                self._converter.cleanup_model()
            self._converter = None
            self._loaded_model = None
            if self._torch is not None:
                with contextlib.suppress(Exception):
                    self._torch.cuda.empty_cache()
            log.info("已释放推理模型与显存缓存")

    def status(self) -> dict:
        info = {
            "loaded_model": self._loaded_model,
            "cuda": False,
            "device": "CPU",
        }
        try:
            import torch

            info["cuda"] = bool(torch.cuda.is_available())
            info["device"] = describe_device(torch)
            if torch.cuda.is_available():
                free, total = torch.cuda.mem_get_info()
                info["vram_free_gb"] = round(free / 1024**3, 2)
                info["vram_total_gb"] = round(total / 1024**3, 2)
        except Exception as exc:  # pragma: no cover
            info["error"] = str(exc)
        return info
