"""翻唱流水线：下载 → 人声分离 → Applio 音色转换 → 后期 → 混音导出。"""

from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import cache as cache_store
from .downloader import prepare_source
from .engine import ApplioEngine
from .logging_utils import get_logger
from .mixer import build_effects, load_audio, mix_and_export, process_vocal
from .models import ModelRegistry, VoiceModel
from .paths import OUTPUT_DIR, TEMP_DIR
from .separator import VocalSeparator
from .settings import Settings

log = get_logger("pipeline")

ProgressFn = Callable[..., Any] | None


class PipelineError(RuntimeError):
    """流水线内部可直接展示给用户的中文错误。"""


@dataclass
class ConvertParams:
    """一次转换的全部参数（可哈希化的纯数据）。"""

    song: str
    model_name: str
    key_shift: int = 0
    vocal_vol: float = 0.0
    inst_vol: float = 0.0
    reverb_intensity: float = 4.0
    delay_intensity: float = 0.0
    f0_method: str = "rmvpe"
    index_rate: float = 0.75
    filter_radius: int = 3
    uvr5_agg: int = 10
    uvr5_tta: bool = False
    uvr5_postprocess: bool = False
    uvr5_window_size: int = 512
    uvr5_high_end_process: str = "mirroring"
    vocal_postprocess: bool = False
    shift_accompaniment: bool = True
    msst_batch_size: float = 2
    msst_num_overlap: float = 4
    msst_normalize: bool = True

    def separation_key(self) -> dict[str, Any]:
        return {
            "uvr5_model": "5_HP-Karaoke-UVR",
            "agg": int(self.uvr5_agg),
            "tta": bool(self.uvr5_tta),
            "postprocess": bool(self.uvr5_postprocess),
            "window_size": int(self.uvr5_window_size),
            "high_end": str(self.uvr5_high_end_process),
        }

    def result_key(self, source_key: str) -> dict[str, Any]:
        return {
            "source": source_key,
            "model": self.model_name,
            "key_shift": int(self.key_shift),
            "vocal_vol": float(self.vocal_vol),
            "inst_vol": float(self.inst_vol),
            "reverb": float(self.reverb_intensity),
            "delay": float(self.delay_intensity),
            "f0": str(self.f0_method),
            "index_rate": float(self.index_rate),
            "vocal_postprocess": bool(self.vocal_postprocess),
            "shift_accompaniment": bool(self.shift_accompaniment),
        }


@dataclass
class ConvertOutcome:
    output_path: Path
    cache_hit: bool
    elapsed: float
    stage_timings: dict[str, float] = field(default_factory=dict)


class CoverPipeline:
    """进程内单例流水线，串行处理请求（与参考项目一致）。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.registry = ModelRegistry(settings)
        self.engine = ApplioEngine(settings)
        self.separator = VocalSeparator(settings)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    def models(self) -> list[str]:
        return self.registry.names()

    def refresh_models(self) -> list[str]:
        return [m.name for m in self.registry.refresh()]

    def model_detail(self, name: str) -> VoiceModel:
        return self.registry.get(name)

    # ------------------------------------------------------------------
    def convert(
        self,
        params: ConvertParams,
        progress: ProgressFn = None,
        use_cache: bool = True,
    ) -> ConvertOutcome:
        started = time.time()
        timings: dict[str, float] = {}

        def report(value: float, desc: str) -> None:
            if progress is not None:
                try:
                    progress(value, desc=desc)
                except Exception:  # 进度回调失败不能影响主流程
                    pass
            log.info(f"[{value * 100:5.1f}%] {desc}")

        with self._lock:
            model = self.registry.get(params.model_name)
            self._ensure_ready()
            cache_store.WORK_ROOT.mkdir(parents=True, exist_ok=True)

            # ---------- 1. 来源准备 ----------
            report(0.05, "正在准备处理歌曲...")
            stage = time.time()
            try:
                source = prepare_source(params.song, self.settings, cache_store.WORK_ROOT)
            except Exception as exc:
                raise PipelineError(str(exc)) from exc
            timings["source"] = time.time() - stage
            log.info(f"音频来源: {source.origin} -> {source.wav_path.name}")

            sep_key = params.separation_key()
            res_key = params.result_key(source.cache_key)

            # ---------- 2. 结果缓存 ----------
            cached = cache_store.result_path(source.cache_key, res_key)
            if use_cache and cached.is_file() and cached.stat().st_size > 0:
                cache_store.touch(cached)
                report(1.0, "缓存命中，直接返回成品")
                log.info(f"命中结果缓存: {cached.name}")
                return ConvertOutcome(
                    output_path=cached,
                    cache_hit=True,
                    elapsed=time.time() - started,
                    stage_timings=timings,
                )

            # ---------- 3. 人声分离 ----------
            report(0.15, "检查人声分离缓存...")
            stage = time.time()
            vocal_path, instrument_path, sep_hit = self._ensure_separation(
                source.wav_path, source.cache_key, params, sep_key, report
            )
            timings["separation"] = time.time() - stage

            # ---------- 4. Applio 推理 ----------
            report(0.5, "Applio 音色转换中...")
            stage = time.time()
            converted = cache_store.WORK_ROOT / f"{cache_store.safe_name(source.cache_key)}_vc.wav"
            try:
                result = self.engine.convert(
                    input_path=vocal_path,
                    output_path=converted,
                    model=model,
                    pitch=int(params.key_shift),
                    f0_method=params.f0_method,
                    index_rate=float(params.index_rate),
                )
            except Exception as exc:
                raise PipelineError(str(exc)) from exc
            timings["inference"] = time.time() - stage
            report(0.8, f"音色转换完成（{result.elapsed:.0f}s），正在处理音频...")

            # ---------- 5. 人声后处理 + 混音 ----------
            stage = time.time()
            try:
                vocal_audio, vocal_sr = load_audio(converted, mono=False)
                effects = build_effects(
                    vocal_postprocess=bool(params.vocal_postprocess),
                    reverb_intensity=float(params.reverb_intensity),
                    delay_intensity=float(params.delay_intensity),
                    instrument_path=instrument_path,
                )
                processed = process_vocal(vocal_audio, vocal_sr, effects)
                output = cache_store.result_path(source.cache_key, res_key)
                output.parent.mkdir(parents=True, exist_ok=True)
                mix_and_export(
                    vocal=processed,
                    vocal_sr=vocal_sr,
                    instrument_path=instrument_path,
                    output_path=output,
                    vocal_vol=float(params.vocal_vol),
                    inst_vol=float(params.inst_vol),
                    key_shift=int(params.key_shift),
                    do_shift_accompaniment=bool(params.shift_accompaniment),
                    bitrate=self.settings.output_bitrate,
                )
            except Exception as exc:
                raise PipelineError(f"后期处理/混音失败: {exc}") from exc
            finally:
                converted.unlink(missing_ok=True)
            timings["mix"] = time.time() - stage

            cache_store.trim(self.settings)
            total = time.time() - started
            report(1.0, "处理完成！")
            log.info(
                f"任务完成，总耗时 {total:.1f}s "
                f"(来源 {timings.get('source', 0):.1f}s / 分离 {timings.get('separation', 0):.1f}s "
                f"/ 推理 {timings.get('inference', 0):.1f}s / 混音 {timings.get('mix', 0):.1f}s) "
                f"分离缓存={'命中' if sep_hit else '新建'}"
            )
            return ConvertOutcome(
                output_path=output,
                cache_hit=False,
                elapsed=total,
                stage_timings=timings,
            )

    # ------------------------------------------------------------------
    def _ensure_separation(
        self,
        source_wav: Path,
        source_key: str,
        params: ConvertParams,
        sep_key: dict[str, Any],
        report: Callable[[float, str], None],
    ) -> tuple[Path, Path, bool]:
        """返回 (vocal, instrument, 是否命中缓存)。"""
        folder = cache_store.separation_dir(source_key, sep_key)
        vocal = folder / "vocal.wav"
        instrument = folder / "instrument.wav"
        if vocal.is_file() and instrument.is_file() and vocal.stat().st_size > 0:
            log.info(f"命中分离缓存: {folder.name}")
            report(0.25, "人声分离缓存命中...")
            return vocal, instrument, True

        report(0.25, "分离人声中(UVR5)...")
        result = self.separator.separate(
            source_wav=source_wav,
            out_dir=folder / "raw",
            agg=params.uvr5_agg,
            tta=params.uvr5_tta,
            postprocess=params.uvr5_postprocess,
            window_size=params.uvr5_window_size,
            high_end_process=params.uvr5_high_end_process,
        )
        folder.mkdir(parents=True, exist_ok=True)
        shutil.move(str(result.vocal_path), vocal)
        shutil.move(str(result.instrument_path), instrument)
        shutil.rmtree(folder / "raw", ignore_errors=True)
        report(0.45, f"人声分离完成（{result.elapsed:.0f}s）")
        return vocal, instrument, False

    # ------------------------------------------------------------------
    def _ensure_ready(self) -> None:
        if not self.settings.applio_path.is_dir():
            raise PipelineError(f"Applio 目录不存在: {self.settings.applio_path}")
        if not self.settings.uvr5_model_path().is_file():
            raise PipelineError(
                f"缺少人声分离模型: {self.settings.uvr5_model_path()}\n"
                "请执行 python tools/download_models.py 下载，或手动放入该文件。"
            )
        cache_store.WORK_ROOT.mkdir(parents=True, exist_ok=True)

    def status(self) -> dict[str, Any]:
        return {
            "applio_dir": str(self.settings.applio_path),
            "uvr5_model": str(self.settings.uvr5_model_path()),
            "uvr5_ready": self.settings.uvr5_model_path().is_file(),
            "models": len(self.registry.names()),
            "engine": self.engine.status(),
            "output_root": str(OUTPUT_DIR),
            "temp_root": str(TEMP_DIR),
        }
