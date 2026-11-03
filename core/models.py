"""音色模型（Applio .pth）发现、索引匹配与 FAISS 兼容路径处理。"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from .settings import Settings

# 这些目录里的 .pth 是训练底座（生成器/判别器），不是可用音色
_SKIP_DIR_PARTS = {
    "pretraineds",
    "hifi-gan",
    "refinegan",
    "custom",
    "__pycache__",
}
_SKIP_NAME_PATTERNS = re.compile(
    r"^(f0[gd]\d+k|G\d+k|D\d+k)\.pth$", re.IGNORECASE
)
# 注意：必须是纯 ASCII 目录，否则 FAISS 仍然打不开（项目路径本身可能含中文）
_INDEX_STAGE_DIR = Path(tempfile.gettempdir()) / "appliosvc_api" / "index"


@dataclass(frozen=True)
class VoiceModel:
    """一个可用的 Applio 音色模型。"""

    name: str  # 展示/回传名（.pth 文件名）
    pth_path: Path
    index_path: Path | None = None
    index_score: float = 0.0
    extra: dict = field(default_factory=dict, compare=False, hash=False)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "pth": str(self.pth_path),
            "index": str(self.index_path) if self.index_path else "",
            "index_score": round(self.index_score, 3),
        }


def _is_model_file(path: Path) -> bool:
    if path.suffix.lower() != ".pth":
        return False
    if _SKIP_NAME_PATTERNS.match(path.name):
        return False
    if any(part.lower() in _SKIP_DIR_PARTS for part in path.parts[:-1]):
        return False
    try:
        # 训练底座一般 >100MB 且目录名带 pretraineds；这里只挡明显异常的空文件
        return path.stat().st_size > 1024 * 1024
    except OSError:
        return False


def _iter_files(roots: list[Path], suffix: str) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d.lower() not in {"__pycache__", ".git"}]
            for name in files:
                if not name.lower().endswith(suffix):
                    continue
                path = Path(current) / name
                key = str(path).lower()
                if key in seen:
                    continue
                seen.add(key)
                found.append(path)
    return found


def _normalize(stem: str) -> str:
    """统一命名：去空白、去 added_ 前缀、去尾部 hash 段。"""
    value = stem.strip().lower()
    value = re.sub(r"^(added|trained)_", "", value)
    value = re.sub(r"_(ivf\d+|flat)[_a-z0-9]*$", "", value)
    value = re.sub(r"[\s\-_.]+", "", value)
    return value


def match_index(pth_path: Path, index_files: list[Path]) -> tuple[Path | None, float]:
    """按文件名相似度为模型挑选 .index 检索文件。"""
    if not index_files:
        return None, 0.0

    target = _normalize(pth_path.stem)
    best: Path | None = None
    best_score = 0.0

    for candidate in index_files:
        stem = _normalize(candidate.stem)
        if not stem:
            continue
        if stem == target:
            return candidate, 1.0
        if stem.startswith(target) or target.startswith(stem):
            score = 0.95
        else:
            score = SequenceMatcher(None, target, stem).ratio()
        if score > best_score:
            best, best_score = candidate, score

    if best_score < 0.45:
        return None, best_score
    return best, best_score


def discover_models(settings: Settings, with_index: bool = True) -> list[VoiceModel]:
    """扫描配置中的目录，返回按文件名排序的音色模型列表。"""
    roots = settings.model_roots()
    pth_files = sorted(
        (p for p in _iter_files(roots, ".pth") if _is_model_file(p)),
        key=lambda p: str(p).lower(),
    )
    index_files = _iter_files(roots, ".index") if with_index else []

    models: list[VoiceModel] = []
    used_names: dict[str, int] = {}
    for pth in pth_files:
        index_path, score = match_index(pth, index_files)
        name = pth.name
        # 不同目录下同名模型时追加序号，保证下拉框唯一
        if name in used_names:
            used_names[name] += 1
            name = f"{pth.stem} ({used_names[name]}){pth.suffix}"
        else:
            used_names[name] = 1
        models.append(
            VoiceModel(
                name=name,
                pth_path=pth,
                index_path=index_path,
                index_score=score,
            )
        )
    return models


class ModelRegistry:
    """模型列表缓存 + 名称到路径的映射。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._models: list[VoiceModel] = []
        self._by_name: dict[str, VoiceModel] = {}

    def refresh(self) -> list[VoiceModel]:
        self._models = discover_models(self.settings)
        self._by_name = {m.name: m for m in self._models}
        return self._models

    def names(self) -> list[str]:
        if not self._models:
            self.refresh()
        return [m.name for m in self._models]

    def get(self, name: str) -> VoiceModel:
        if not self._models:
            self.refresh()
        # gradio 下拉框偶尔回传 list
        if isinstance(name, (list, tuple)):
            name = name[0] if name else ""
        key = str(name or "").strip()
        model = self._by_name.get(key)
        if model is None:
            # 兼容只传了 stem 或带路径的旧调用
            for candidate in self._models:
                if key in {candidate.name, candidate.pth_path.name, candidate.pth_path.stem}:
                    return candidate
            self.refresh()
            model = self._by_name.get(key)
            if model is None:
                available = "、".join(self.names()[:8]) or "（无）"
                raise ValueError(f"未找到音色模型：{key!r}，可用模型：{available}")
        return model


def ascii_safe_audio_path(path: Path, suffix: str | None = None) -> Path:
    """把含中文/非 ASCII 字符的文件复制到纯 ASCII 临时路径。

    FAISS 使用 C++ 的 fopen 打开 index 文件，Windows 下遇到中文路径会直接失败，
    因此推理前需要把 .index 复制（或硬链接）到一个纯 ASCII 路径。
    """
    try:
        text = str(path)
        text.encode("ascii")
        return path
    except UnicodeEncodeError:
        pass

    suffix = suffix or path.suffix
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:16]
    stat = path.stat()
    _INDEX_STAGE_DIR.mkdir(parents=True, exist_ok=True)
    target = _INDEX_STAGE_DIR / f"{digest}_{stat.st_size}{suffix}"
    if not target.is_file() or target.stat().st_size != stat.st_size:
        try:
            os.link(path, target)  # 同一分区时用硬链接，零拷贝
        except OSError:
            shutil.copy2(path, target)
    return target
