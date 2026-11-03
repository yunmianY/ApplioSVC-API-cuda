"""人声后期处理、伴奏变调与最终混音导出。"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from .logging_utils import get_logger

log = get_logger("mixer")

# 混响强度锚点：0 / 4(默认) / 10
_ROOM_SIZE_MAP = (0.15, 0.40, 0.90)
_WET_LEVEL_MAP = (0.10, 0.25, 0.45)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def reverb_params(intensity: float) -> tuple[float, float, float]:
    """把 0~10 的混响强度映射成 pedalboard Reverb 的 room/wet/dry。"""
    value = max(0.0, min(10.0, float(intensity)))
    if value <= 4:
        t = value / 4.0
        room = _lerp(_ROOM_SIZE_MAP[0], _ROOM_SIZE_MAP[1], t)
        wet = _lerp(_WET_LEVEL_MAP[0], _WET_LEVEL_MAP[1], t)
    else:
        t = (value - 4.0) / 6.0
        room = _lerp(_ROOM_SIZE_MAP[1], _ROOM_SIZE_MAP[2], t)
        wet = _lerp(_WET_LEVEL_MAP[1], _WET_LEVEL_MAP[2], t)
    return round(room, 3), round(wet, 3), round(1.0 - wet, 3)


def _beat_delay_seconds(instrument_path: Path) -> float:
    """按伴奏 BPM 估算一个八分音符的延迟时间。"""
    try:
        import librosa

        y, sr = librosa.load(str(instrument_path), sr=None, mono=True)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(np.asarray(tempo).reshape(-1)[0])
        if bpm > 0:
            log.info(f"检测到伴奏 BPM≈{bpm:.1f}，回声时间按 {60.0 / bpm * 0.5:.3f}s 计算")
            return 60.0 / bpm * 0.5
        log.info("未能检测到有效 BPM，回声时间使用默认 0.5s")
    except Exception as exc:
        log.warning(f"BPM 检测失败（{exc}），回声时间使用默认 0.5s")
    return 0.5


def build_effects(
    vocal_postprocess: bool,
    reverb_intensity: float,
    delay_intensity: float,
    instrument_path: Path | None = None,
) -> list:
    """构造参考项目同款的人声效果链（可关闭）。"""
    if not vocal_postprocess:
        return []

    from pedalboard import (
        Compressor,
        Delay,
        HighpassFilter,
        LowpassFilter,
        PeakFilter,
        Reverb,
    )

    effects = [
        HighpassFilter(cutoff_frequency_hz=80),
        PeakFilter(cutoff_frequency_hz=200, gain_db=1.5, q=0.7),
        PeakFilter(cutoff_frequency_hz=3000, gain_db=2.0, q=1.0),
        PeakFilter(cutoff_frequency_hz=7000, gain_db=-3.0, q=2.0),
        LowpassFilter(cutoff_frequency_hz=16000),
        Compressor(threshold_db=-18.0, ratio=4.0, attack_ms=5.0, release_ms=150.0),
    ]

    if delay_intensity and delay_intensity > 0:
        seconds = _beat_delay_seconds(instrument_path) if instrument_path else 0.5
        mix = (float(delay_intensity) / 10.0) * 0.35
        effects.append(Delay(delay_seconds=seconds, feedback=0.25, mix=mix))

    if reverb_intensity and reverb_intensity > 0:
        room, wet, dry = reverb_params(reverb_intensity)
        log.info(f"混响参数: 强度={reverb_intensity} -> room={room}, wet={wet}, dry={dry}")
        effects.append(
            Reverb(room_size=room, damping=0.4, wet_level=wet, dry_level=dry, width=0.8)
        )
    return effects


def process_vocal(
    audio: np.ndarray,
    sample_rate: int,
    effects: list,
) -> np.ndarray:
    """对推理结果应用效果链，返回 (channels, samples) 的 float32。"""
    from pedalboard import Pedalboard

    if audio.ndim == 1:
        audio = audio.reshape(1, -1)
    if not effects:
        return audio.astype(np.float32, copy=False)
    board = Pedalboard(effects)
    processed = board(audio.astype(np.float32, copy=False), sample_rate)
    if processed.ndim == 1:
        processed = processed.reshape(1, -1)
    return np.ascontiguousarray(processed, dtype=np.float32)


def load_audio(path: Path, mono: bool = False) -> tuple[np.ndarray, int]:
    import librosa

    audio, sr = librosa.load(str(path), sr=None, mono=mono)
    return audio, int(sr)


def shift_accompaniment(path: Path, semitones: int) -> tuple[np.ndarray, int]:
    """用 pedalboard PitchShift 给伴奏做同步升降调，返回 (audio, sample_rate)。"""
    from pedalboard import Pedalboard, PitchShift

    audio, sr = load_audio(path, mono=False)
    if audio.ndim == 1:
        audio = audio.reshape(1, -1)
    board = Pedalboard([PitchShift(semitones=int(semitones))])
    shifted = board(audio.astype(np.float32), sr)
    if shifted.ndim == 1:
        shifted = shifted.reshape(1, -1)
    return np.ascontiguousarray(shifted, dtype=np.float32), sr


def numpy_to_segment(audio: np.ndarray, sample_rate: int):
    """float32 (channels, samples) -> pydub.AudioSegment。"""
    from pydub import AudioSegment

    if audio.ndim == 1:
        audio = audio.reshape(1, -1)
    clipped = np.clip(audio, -1.0, 1.0 - (1.0 / 32768.0))
    pcm = np.rint(clipped.T * 32768.0).astype(np.int16)
    return AudioSegment(
        pcm.tobytes(),
        frame_rate=int(sample_rate),
        sample_width=2,
        channels=int(audio.shape[0]),
    )


def mix_and_export(
    vocal: np.ndarray,
    vocal_sr: int,
    instrument_path: Path,
    output_path: Path,
    vocal_vol: float = 0.0,
    inst_vol: float = 0.0,
    key_shift: int = 0,
    do_shift_accompaniment: bool = True,
    bitrate: str = "320k",
) -> Path:
    """把人声与伴奏混合并导出 MP3。"""
    from pydub import AudioSegment
    from pydub.effects import normalize

    started = time.time()
    vocal_segment = normalize(numpy_to_segment(vocal, vocal_sr) + float(vocal_vol), headroom=-1.0)

    if do_shift_accompaniment and key_shift and abs(int(key_shift)) != 12:
        log.info(f"伴奏同步升降调 {int(key_shift):+d} 半音")
        try:
            shifted, inst_sr = shift_accompaniment(instrument_path, key_shift)
            instrument_segment = numpy_to_segment(shifted, inst_sr)
        except Exception as exc:
            log.warning(f"伴奏变调失败，改用原始伴奏: {exc}")
            instrument_segment = AudioSegment.from_file(str(instrument_path))
    else:
        instrument_segment = AudioSegment.from_file(str(instrument_path))

    if instrument_segment.frame_rate != vocal_segment.frame_rate:
        instrument_segment = instrument_segment.set_frame_rate(vocal_segment.frame_rate)
    if instrument_segment.channels != vocal_segment.channels:
        # Applio 输出通常是单声道，伴奏是立体声；优先保留立体声伴奏的声场
        if instrument_segment.channels > vocal_segment.channels:
            vocal_segment = vocal_segment.set_channels(instrument_segment.channels)
        else:
            instrument_segment = instrument_segment.set_channels(vocal_segment.channels)

    instrument_segment = instrument_segment + float(inst_vol)
    combined = vocal_segment.overlay(instrument_segment)
    if combined.max_dBFS > -1.0:
        combined = combined.apply_gain(-1.0 - combined.max_dBFS)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.export(str(output_path), format="MP3", bitrate=bitrate)
    log.info(f"混音导出完成：{output_path.name}（{time.time() - started:.1f}s）")
    return output_path

