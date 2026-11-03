"""缓存管理：人声分离缓存、最终结果缓存、统计与清理。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from .logging_utils import get_logger
from .paths import OUTPUT_DIR, TEMP_DIR
from .settings import Settings

log = get_logger("cache")

PIPELINE_VERSION = "appliosvc-cuda-v1"
SEPARATION_ROOT = OUTPUT_DIR / "uvr5"
RESULT_ROOT = TEMP_DIR / "results"
WORK_ROOT = TEMP_DIR / "work"

_ILLEGAL = re.compile(r'[\\/:*?"<>|\s]+')


def safe_name(value: str, limit: int = 60) -> str:
    """把任意字符串变成合法的 Windows 文件名片段。"""
    cleaned = _ILLEGAL.sub("_", str(value)).strip("_")
    return (cleaned or "item")[:limit]


def separation_dir(source_key: str, params: dict[str, Any]) -> Path:
    """按源音频 + 分离参数生成稳定的缓存目录。"""
    payload = json.dumps(
        {"source": source_key, **{k: params[k] for k in sorted(params)}},
        sort_keys=True,
        ensure_ascii=True,
    )
    digest = hashlib.md5(payload.encode("utf-8")).hexdigest()[:12]
    return SEPARATION_ROOT / f"{safe_name(source_key)}_{digest}"


def result_path(source_key: str, params: dict[str, Any]) -> Path:
    """最终成品的缓存路径（参数一变就换 key）。"""
    payload = json.dumps(
        {"pipeline": PIPELINE_VERSION, "source": source_key, **{k: params[k] for k in sorted(params)}},
        sort_keys=True,
        ensure_ascii=True,
    )
    digest = hashlib.md5(payload.encode("utf-8")).hexdigest()[:12]
    return RESULT_ROOT / f"{safe_name(source_key)}_{digest}.mp3"


def _files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*") if p.is_file()]


def _area_info(root: Path) -> dict[str, int]:
    files = _files(root)
    return {
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files if p.is_file()),
        "dirs": len({p.parent for p in files}),
    }


def cache_info(settings: Settings) -> dict[str, Any]:
    """返回缓存统计，供 /cache_info 接口与 UI 使用。"""
    areas = {
        "results": _area_info(RESULT_ROOT),
        "separation": _area_info(SEPARATION_ROOT),
        "work": _area_info(WORK_ROOT),
    }
    return {
        "service": "ApplioSVC-API (CUDA)",
        "root": str(OUTPUT_DIR.parent),
        "areas": areas,
        "max_files": int(settings.cache_max_files),
        "total_files": sum(item["files"] for item in areas.values()),
        "total_bytes": sum(item["bytes"] for item in areas.values()),
    }


def clear_cache(scope: str = "all", settings: Settings | None = None) -> dict[str, Any]:
    """清理缓存：scope 可选 all / results / separation / work。"""
    mapping = {
        "results": [RESULT_ROOT],
        "separation": [SEPARATION_ROOT],
        "work": [WORK_ROOT],
    }
    scope_key = str(scope or "all").lower()
    if scope_key == "all":
        targets = [path for group in mapping.values() for path in group]
    elif scope_key in mapping:
        targets = mapping[scope_key]
    else:
        return {"error": f"未知的清理范围: {scope}", "scope": scope_key}

    deleted = 0
    freed = 0
    for root in targets:
        for path in _files(root):
            try:
                size = path.stat().st_size
                path.unlink()
                deleted += 1
                freed += size
            except OSError as exc:
                log.warning(f"删除缓存文件失败 {path}: {exc}")
        if root.is_dir():
            for current, dirs, _ in os.walk(root, topdown=False):
                for name in dirs:
                    try:
                        Path(current, name).rmdir()
                    except OSError:
                        pass
    log.info(f"清理缓存[{scope_key}]：{deleted} 个文件，释放 {freed / 1024 / 1024:.1f} MB")
    return {"deleted_files": deleted, "freed_bytes": freed, "scope": scope_key}


def trim(settings: Settings) -> None:
    """按数量上限清理最旧的成品与分离缓存。"""
    limit = max(10, int(settings.cache_max_files or 200))
    _trim_dir_files(RESULT_ROOT, limit)
    _trim_subdirs(SEPARATION_ROOT, limit)
    # 解码后的源音频（每首歌几十 MB）也按数量兜底，避免无限增长
    _trim_dir_files(WORK_ROOT, limit)


def _trim_dir_files(root: Path, limit: int) -> None:
    files = [p for p in _files(root) if p.is_file()]
    if len(files) <= limit:
        return
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files[limit:]:
        try:
            path.unlink()
        except OSError:
            pass


def _trim_subdirs(root: Path, limit: int) -> None:
    if not root.is_dir():
        return
    groups = [d for d in root.iterdir() if d.is_dir()]
    if len(groups) <= limit:
        return

    def newest(path: Path) -> float:
        return max((p.stat().st_mtime for p in _files(path)), default=0.0)

    groups.sort(key=newest, reverse=True)
    for path in groups[limit:]:
        shutil.rmtree(path, ignore_errors=True)


def touch(path: Path) -> None:
    """更新 mtime，让热点缓存不被优先清理。"""
    try:
        now = time.time()
        os.utime(path, (now, now))
    except OSError:
        pass
