"""日志与设备信息工具。"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .paths import PROJECT_DIR

LOG_DIR = PROJECT_DIR / "logs"
LOGGER_NAME = "appliosvc"

_configured = False


def setup_logging(level: str = "INFO", filename: str = "appliosvc.log") -> logging.Logger:
    """初始化全局日志：控制台 + logs/appliosvc.log（滚动）。"""
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    if _configured:
        return logger

    numeric = getattr(logging, str(level).upper(), logging.INFO)
    logger.setLevel(numeric)
    logger.propagate = False
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_DIR / filename,
            maxBytes=8 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s")
        )
        logger.addHandler(file_handler)
    except OSError as exc:
        logger.warning(f"无法写入日志文件: {exc}")

    _configured = True
    return logger


def get_logger(module: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{module}" if module else LOGGER_NAME)


def describe_device(torch_module) -> str:
    """返回可读的显卡/设备描述。"""
    torch = torch_module
    if not torch.cuda.is_available():
        return "CPU（未检测到可用 CUDA 显卡，推理会非常慢）"
    try:
        index = torch.cuda.current_device()
        name = torch.cuda.get_device_name(index)
        total = torch.cuda.get_device_properties(index).total_memory / (1024**3)
        return f"{name} ({total:.1f} GB, CUDA {torch.version.cuda}, torch {torch.__version__})"
    except Exception as exc:  # pragma: no cover - 仅用于展示
        return f"CUDA 设备信息读取失败: {exc}"
