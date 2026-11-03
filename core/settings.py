"""配置管理：config.json + 环境变量，二者合并后供全局使用。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .paths import PROJECT_DIR, discover_applio_dir

CONFIG_PATH = PROJECT_DIR / "config.json"

# 网易云歌曲下载源，按顺序尝试；{song_id} 会被替换成歌曲 ID
# 前两个是「直接返回音频」的源，后两个是「返回 JSON 再解析直链」的源
DEFAULT_DOWNLOAD_SOURCES = [
    "https://music.163.com/song/media/outer/url?id={song_id}.mp3",
    "https://biliplayer.91vrchat.com/player/?url=https://music.163.com/song?id={song_id}",
    "https://music-api.gdstudio.xyz/api.php?types=url&source=netease&id={song_id}&br=320",
    "https://api.vkeys.cn/v2/music/netease?id={song_id}",
]


@dataclass
class Settings:
    """中间层运行配置。字段含义见 README。"""

    # --- 服务 ---
    host: str = "127.0.0.1"
    rvc_port: int = 3333
    svc_port: int = 9999
    queue_size: int = 40
    share: bool = False
    show_error: bool = True
    log_level: str = "INFO"

    # --- Applio ---
    # 留空则自动探测（同级目录 / APPLIO_DIR 环境变量）
    applio_dir: str = ""
    # 相对 applio_dir 或绝对路径；默认扫描训练输出目录 logs/
    model_dirs: list[str] = field(default_factory=lambda: ["logs"])
    extra_model_dirs: list[str] = field(default_factory=list)

    # --- 人声分离 ---
    # 相对路径按项目根目录解析，便于整个目录搬移
    uvr5_model: str = "models/uvr5/5_HP-Karaoke-UVR.pth"
    uvr5_device: str = "auto"  # auto / cuda / cpu
    uvr5_half: bool = True
    uvr5_agg: int = 10
    uvr5_tta: bool = False
    uvr5_postprocess: bool = False
    uvr5_window_size: int = 512
    uvr5_high_end_process: str = "mirroring"

    # --- 推理默认值（插件未显式传参时使用）---
    volume_envelope: float = 0.25
    protect: float = 0.33
    default_f0_method: str = "rmvpe"
    max_audio_seconds: int = 330  # 超长音频截断，避免单次任务过久

    # --- 输出与缓存 ---
    output_bitrate: str = "320k"
    cache_max_files: int = 200
    ffmpeg_path: str = ""

    # --- 下载 ---
    download_sources: list[str] = field(
        default_factory=lambda: list(DEFAULT_DOWNLOAD_SOURCES)
    )
    download_timeout: int = 30
    # VIP 歌曲需要登录态：自建 NeteaseCloudMusicApi 的地址 + 登录后的 cookie
    # 例：netease_api_base = "http://127.0.0.1:3000"，netease_cookie = "MUSIC_U=xxxx"
    netease_api_base: str = ""
    netease_cookie: str = ""
    netease_level: str = "exhigh"  # standard / higher / exhigh / lossless

    # 运行期填充
    resolved_applio_dir: str = ""

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Settings":
        data: dict[str, Any] = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:  # 配置损坏时回退默认值
                print(f"[config] 读取 {path} 失败，使用默认配置: {exc}")
                data = {}
        allowed = {f for f in cls.__dataclass_fields__ if f != "resolved_applio_dir"}
        settings = cls(**{k: v for k, v in data.items() if k in allowed})
        settings._apply_env()
        settings._resolve()
        if not path.is_file():
            settings.save(path)
        return settings

    def _apply_env(self) -> None:
        """环境变量覆盖（APPLIOSVC_ 前缀，优先级最高）。"""
        env = os.environ
        if env.get("APPLIO_DIR"):
            self.applio_dir = env["APPLIO_DIR"]
        mapping = {
            "APPLIOSVC_HOST": ("host", str),
            "APPLIOSVC_RVC_PORT": ("rvc_port", int),
            "APPLIOSVC_SVC_PORT": ("svc_port", int),
            "APPLIOSVC_SHARE": ("share", _as_bool),
            "APPLIOSVC_SHOW_ERROR": ("show_error", _as_bool),
            "APPLIOSVC_UVR5_MODEL": ("uvr5_model", str),
            "APPLIOSVC_UVR5_DEVICE": ("uvr5_device", str),
            "APPLIOSVC_F0_METHOD": ("default_f0_method", str),
            "APPLIOSVC_OUTPUT_BITRATE": ("output_bitrate", str),
            "APPLIOSVC_CACHE_MAX_FILES": ("cache_max_files", int),
            "APPLIOSVC_LOG_LEVEL": ("log_level", str),
        }
        for env_name, (attr, caster) in mapping.items():
            raw = env.get(env_name)
            if raw is None or raw == "":
                continue
            try:
                setattr(self, attr, caster(raw))
            except (TypeError, ValueError):
                print(f"[config] 忽略非法的环境变量 {env_name}={raw!r}")

    def _resolve(self) -> None:
        if self.applio_dir:
            candidate = Path(self.applio_dir).expanduser()
            if candidate.is_dir():
                self.resolved_applio_dir = str(candidate.resolve())
        if not self.resolved_applio_dir:
            self.resolved_applio_dir = str(discover_applio_dir())

    # ------------------------------------------------------------------
    @property
    def applio_path(self) -> Path:
        return Path(self.resolved_applio_dir)

    def model_roots(self) -> list[Path]:
        """返回所有需要扫描 .pth 的目录（已解析为绝对路径）。"""
        roots: list[Path] = []
        for raw in list(self.model_dirs) + list(self.extra_model_dirs):
            if not raw:
                continue
            candidate = Path(raw).expanduser()
            if not candidate.is_absolute():
                candidate = self.applio_path / candidate
            if candidate.is_dir():
                roots.append(candidate.resolve())
        return roots

    def uvr5_model_path(self) -> Path:
        candidate = Path(self.uvr5_model).expanduser()
        if not candidate.is_absolute():
            candidate = PROJECT_DIR / candidate
        return candidate

    def save(self, path: Path = CONFIG_PATH) -> None:
        payload = asdict(self)
        payload.pop("resolved_applio_dir", None)
        try:
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"[config] 写入 {path} 失败: {exc}")


def _as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


_SETTINGS: Settings | None = None


def get_settings(refresh: bool = False) -> Settings:
    """进程内单例配置。"""
    global _SETTINGS
    if _SETTINGS is None or refresh:
        _SETTINGS = Settings.load()
    return _SETTINGS
