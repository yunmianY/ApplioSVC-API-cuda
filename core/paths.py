"""路径解析：项目自身目录、Applio 目录、各类资源目录。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
CORE_DIR = PROJECT_DIR / "core"
TEMP_DIR = PROJECT_DIR / "temp"
OUTPUT_DIR = PROJECT_DIR / "output"
MODELS_DIR = PROJECT_DIR / "models"
DEFAULT_UVR5_MODEL = MODELS_DIR / "uvr5" / "5_HP-Karaoke-UVR.pth"

# Applio 判定特征：core.py + rvc/infer/infer.py 同时存在
_APPLIO_MARKERS = ("core.py", os.path.join("rvc", "infer", "infer.py"))

_CACHED_APPLIO_DIR: Path | None = None


def looks_like_applio(path: str | os.PathLike[str] | None) -> bool:
    """判断给定目录是否是一个 Applio 安装目录。"""
    if not path:
        return False
    root = Path(path)
    return all((root / marker).is_file() for marker in _APPLIO_MARKERS)


def _candidate_dirs() -> list[Path]:
    """按优先级列出可能的 Applio 目录。"""
    candidates: list[Path] = []

    env_value = os.environ.get("APPLIO_DIR") or os.environ.get("APPLIOSVC_APPLIO_DIR")
    if env_value:
        candidates.append(Path(env_value))

    # 项目同级目录：兼容 ApplioV3.6.5 / Applio / applio 等常见命名
    parent = PROJECT_DIR.parent
    if parent.is_dir():
        try:
            for child in sorted(parent.iterdir()):
                if not child.is_dir():
                    continue
                lowered = child.name.lower()
                if "applio" in lowered or (child / "core.py").is_file():
                    candidates.append(child)
        except OSError:
            pass

    # 项目内部（把 Applio 塞进中间层目录的场景）
    candidates.append(PROJECT_DIR / "Applio")
    candidates.append(PROJECT_DIR)
    return candidates


def discover_applio_dir() -> Path:
    """自动定位 Applio 安装目录，找不到时抛出说明性错误。"""
    global _CACHED_APPLIO_DIR
    if _CACHED_APPLIO_DIR is not None:
        return _CACHED_APPLIO_DIR

    for candidate in _candidate_dirs():
        if looks_like_applio(candidate):
            _CACHED_APPLIO_DIR = candidate.resolve()
            return _CACHED_APPLIO_DIR

    tried = "\n".join(f"  - {p}" for p in _candidate_dirs())
    raise RuntimeError(
        "未能自动定位 Applio 安装目录。\n"
        "请设置环境变量 APPLIO_DIR，或在 config.json 里填写 applio_dir 字段。\n"
        f"已尝试的候选路径：\n{tried}"
    )


def ensure_runtime_dirs() -> None:
    """确保运行期目录存在。"""
    for folder in (TEMP_DIR, OUTPUT_DIR, MODELS_DIR / "uvr5"):
        folder.mkdir(parents=True, exist_ok=True)


def add_project_to_syspath() -> None:
    """把项目根目录加入 sys.path，便于导入 uvr5 / core 包。"""
    project = str(PROJECT_DIR)
    if project not in sys.path:
        sys.path.insert(0, project)


def find_ffmpeg(applio_dir: Path | None = None) -> str | None:
    """定位 ffmpeg 可执行文件：项目 → Applio → PATH。"""
    candidates = [PROJECT_DIR / "ffmpeg.exe"]
    if applio_dir:
        candidates.append(applio_dir / "ffmpeg.exe")
        candidates.append(applio_dir / "ffmpeg" / "bin" / "ffmpeg.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        if not folder:
            continue
        candidate = Path(folder) / "ffmpeg.exe"
        if candidate.is_file():
            return str(candidate)
    return None
