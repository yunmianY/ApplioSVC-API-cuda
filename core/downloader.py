"""歌曲来源处理：网易云 ID/链接、直链、AstrBot 已下载的本地文件。"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

from .logging_utils import get_logger
from .settings import Settings

log = get_logger("downloader")

AUDIO_SUFFIXES = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"}
_NETEASE_URL_ID = re.compile(r"(?:id=|/song/)(\d+)")
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class SourceAudio:
    """已解码为 WAV 的源音频。"""

    wav_path: Path
    cache_key: str  # 用于分离/结果缓存命名，纯 ASCII
    origin: str
    trimmed: bool = False
    duration: float = 0.0


def _sha256_prefix(path: Path, length: int = 16) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()[:length]


def extract_netease_id(raw: str) -> str | None:
    """从 URL 或纯数字中提取网易云歌曲 ID。"""
    text = str(raw or "").strip()
    if not text:
        return None
    if text.isdigit():
        return text
    match = _NETEASE_URL_ID.search(text)
    if match:
        return match.group(1)
    return None


def _looks_like_audio_response(response: requests.Response) -> bool:
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "text/html" in content_type or "application/json" in content_type:
        return False
    if "audio" in content_type or "octet-stream" in content_type:
        return True
    # 有些源直接返回二进制但不带类型
    return len(response.content) > 256 * 1024


def _extract_audio_url(payload: object, depth: int = 0) -> str | None:
    """从解析接口返回的 JSON 中挖出音频直链。"""
    if depth > 4:
        return None
    if isinstance(payload, str):
        return payload if payload.startswith("http") else None
    if isinstance(payload, dict):
        # 常见字段优先，避免误取封面图
        for key in ("music_url", "song_url", "url", "src", "data", "music"):
            if key in payload:
                found = _extract_audio_url(payload[key], depth + 1)
                if found:
                    return found
        for value in payload.values():
            found = _extract_audio_url(value, depth + 1)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _extract_audio_url(item, depth + 1)
            if found:
                return found
    return None


def _fetch_audio(url: str, headers: dict[str, str], timeout: int, target: Path) -> int:
    """下载音频直链到 target，返回字节数。"""
    with requests.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True) as response:
        response.raise_for_status()
        written = 0
        with target.open("wb") as stream:
            for chunk in response.iter_content(1024 * 256):
                if chunk:
                    stream.write(chunk)
                    written += len(chunk)
    return written


_COOKIE_ATTRS = {
    "max-age",
    "expires",
    "path",
    "domain",
    "httponly",
    "samesite",
    "secure",
    "version",
    "comment",
    "priority",
}
_COOKIE_NAME = re.compile(r"^[A-Za-z0-9_\-\.]+$")


def normalize_cookie(raw: str) -> str:
    """把任意来源的 cookie 文本清洗成合法的 `Cookie:` 头。

    网易接口有时会把整串 Set-Cookie（含 Max-Age/Expires/Path、并有重复字段）
    直接返回，原样当 Cookie 头发出去会被服务端忽略，表现为「已登录但 account=null」。
    """
    text = (raw or "").strip()
    if not text:
        return ""
    if text.lower().startswith("cookie:"):
        text = text[7:]
    pairs: dict[str, str] = {}
    for segment in text.split(";"):
        segment = segment.strip()
        if not segment or "=" not in segment:
            continue
        name, value = segment.split("=", 1)
        name = name.strip()
        if not name or not _COOKIE_NAME.match(name):
            continue
        if name.lower() in _COOKIE_ATTRS:
            continue
        pairs[name] = value.strip()
    return "; ".join(f"{key}={value}" for key, value in pairs.items())


def _netease_cookie_header(settings: Settings) -> dict[str, str]:
    """把配置里的 cookie 清洗后变成请求头（永不写进日志）。"""
    cookie = normalize_cookie(settings.netease_cookie or "")
    return {"Cookie": cookie} if cookie else {}


def _authenticated_sources(settings: Settings) -> list[str]:
    """自建 NeteaseCloudMusicApi 的取播放地址接口（需要登录态）。"""
    base = (settings.netease_api_base or "").strip().rstrip("/")
    if not base:
        return []
    level = (settings.netease_level or "exhigh").strip() or "exhigh"
    return [
        f"{base}/song/url/v1?id={{song_id}}&level={level}",
        f"{base}/song/url?id={{song_id}}",
    ]


def _download_netease(song_id: str, settings: Settings, work_dir: Path) -> Path:
    """按「登录态接口 → 公共直链/解析接口」的顺序尝试下载。"""
    errors: list[str] = []
    base_headers = {"User-Agent": _USER_AGENT, "Referer": "https://music.163.com/"}
    cookie_headers = _netease_cookie_header(settings)
    auth_sources = _authenticated_sources(settings)
    has_login = bool(cookie_headers)

    if auth_sources and not has_login:
        log.warning(
            "已配置 netease_api_base 但没有 netease_cookie，VIP 歌曲仍然拿不到；"
            "请先登录并把 MUSIC_U 填进 config.json"
        )

    raw_path = work_dir / f"netease_{song_id}.bin"
    sources: list[tuple[str, dict[str, str]]] = []
    for template in auth_sources:
        sources.append((template, {**base_headers, **(cookie_headers if has_login else {})}))
    for template in settings.download_sources:
        sources.append((template, base_headers))

    for template, headers in sources:
        url = template.format(song_id=song_id)
        try:
            log.info(f"尝试下载源: {url}")
            response = requests.get(
                url, headers=headers, timeout=settings.download_timeout, allow_redirects=True
            )
            if response.status_code != 200:
                errors.append(f"{url} -> HTTP {response.status_code}")
                continue

            content_type = (response.headers.get("Content-Type") or "").lower()
            is_json = "json" in content_type or response.text[:1].lstrip() in {"{", "["}

            if is_json:
                try:
                    payload = response.json()
                except ValueError:
                    errors.append(f"{url} -> 返回了无法解析的 JSON")
                    continue
                audio_url = _extract_audio_url(payload)
                if not audio_url:
                    reason = "未取到播放链接"
                    if url.startswith(tuple(_authenticated_sources(settings)) or ("",)):
                        reason += "（登录态失效 / 该账号无此歌曲版权或未开通 VIP）"
                    snippet = str(payload)[:120]
                    errors.append(f"{url} -> {reason} ({snippet})")
                    continue
                log.info(f"解析到音频直链: {audio_url[:120]}")
                written = _fetch_audio(audio_url, headers, settings.download_timeout, raw_path)
            elif _looks_like_audio_response(response):
                raw_path.write_bytes(response.content)
                written = len(response.content)
            else:
                errors.append(f"{url} -> 返回内容不是音频 ({content_type or '未知类型'})")
                continue

            if written < 100 * 1024:
                errors.append(f"{url} -> 文件过小 ({written} 字节)")
                raw_path.unlink(missing_ok=True)
                continue
            log.info(f"下载成功: {written / 1024 / 1024:.1f} MB <- {url}")
            return raw_path
        except requests.RequestException as exc:
            errors.append(f"{url} -> {exc}")

    hint = (
        "\n提示：VIP 歌曲需要登录态 —— 自建 NeteaseCloudMusicApi，然后填写 "
        "netease_api_base 与 netease_cookie（详见 README）；"
        "\n或者在 AstrBot 插件里把音乐源切到「QQ音乐」，由插件下载后传本地路径。"
    )
    raise RuntimeError(
        "所有网易云下载源均失败（常见原因：该歌曲需要 VIP / 解析接口失效）：\n  "
        + "\n  ".join(errors)
        + hint
    )


def _download_direct(url: str, settings: Settings, work_dir: Path) -> Path:
    headers = {"User-Agent": _USER_AGENT}
    suffix = Path(urlparse(url).path).suffix or ".bin"
    target = work_dir / f"direct_{int(time.time())}{suffix}"
    log.info(f"下载音频直链: {url}")
    with requests.get(url, headers=headers, timeout=settings.download_timeout, stream=True) as response:
        response.raise_for_status()
        with target.open("wb") as stream:
            for chunk in response.iter_content(1024 * 256):
                if chunk:
                    stream.write(chunk)
    if target.stat().st_size < 50 * 1024:
        raise RuntimeError(f"直链下载内容过小，可能不是音频: {url}")
    return target


def _export_wav(source: Path, target: Path, settings: Settings, max_seconds: int) -> tuple[Path, bool, float]:
    """把任意音频转成 44.1kHz 立体声 WAV，并按需截断。"""
    from pydub import AudioSegment

    ffmpeg = settings.ffmpeg_path or None
    if ffmpeg:
        AudioSegment.converter = ffmpeg
        AudioSegment.ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe"))

    try:
        audio = AudioSegment.from_file(str(source))
    except Exception as exc:
        raise RuntimeError(f"无法解码音频 {source.name}（请确认 ffmpeg 可用）: {exc}") from exc

    trimmed = False
    duration = len(audio) / 1000.0
    if max_seconds and duration > max_seconds:
        log.info(f"音频长度 {duration:.1f}s 超过上限 {max_seconds}s，已截断")
        audio = audio[: int(max_seconds * 1000)]
        trimmed = True
        duration = len(audio) / 1000.0

    audio = audio.set_frame_rate(44100).set_channels(2)
    target.parent.mkdir(parents=True, exist_ok=True)
    audio.export(str(target), format="wav")
    return target, trimmed, duration


def prepare_source(raw: str, settings: Settings, work_dir: Path) -> SourceAudio:
    """把插件的 song_name_src 变成可分离的 WAV 文件。"""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("歌曲参数为空：请提供网易云 ID/链接或本地音频路径")

    work_dir.mkdir(parents=True, exist_ok=True)
    max_seconds = int(settings.max_audio_seconds or 0)

    # 1) 本地文件（AstrBot 的 mat iko 插件在 QQ 音乐模式下会传本地缓存路径）
    candidate = Path(text).expanduser()
    if not text.lower().startswith(("http://", "https://")) and candidate.is_file():
        if candidate.suffix.lower() not in AUDIO_SUFFIXES:
            log.warning(f"本地文件后缀不常见（{candidate.suffix}），仍尝试解码")
        key = f"local_{_sha256_prefix(candidate)}"
        wav = work_dir / f"{key}.wav"
        origin = f"本地文件 {candidate.name}"
        if wav.is_file() and wav.stat().st_size > 0:
            log.info(f"复用已解码本地音频缓存: {wav.name}")
            return SourceAudio(wav_path=wav, cache_key=key, origin=origin)
        exported, trimmed, duration = _export_wav(candidate, wav, settings, max_seconds)
        return SourceAudio(
            wav_path=exported, cache_key=key, origin=origin, trimmed=trimmed, duration=duration
        )

    # 2) 网易云 ID 或分享链接
    song_id = extract_netease_id(text)
    if song_id:
        key = f"netease_{song_id}"
        wav = work_dir / f"{key}.wav"
        origin = f"网易云 {song_id}"
        if wav.is_file() and wav.stat().st_size > 0:
            log.info(f"复用已解码网易云音频缓存: {wav.name}")
            return SourceAudio(wav_path=wav, cache_key=key, origin=origin)
        raw_file = _download_netease(song_id, settings, work_dir)
        try:
            exported, trimmed, duration = _export_wav(raw_file, wav, settings, max_seconds)
        finally:
            raw_file.unlink(missing_ok=True)
        return SourceAudio(
            wav_path=exported, cache_key=key, origin=origin, trimmed=trimmed, duration=duration
        )

    # 3) 音频直链
    if text.lower().startswith(("http://", "https://")):
        key = f"url_{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"
        wav = work_dir / f"{key}.wav"
        origin = "音频直链"
        if wav.is_file() and wav.stat().st_size > 0:
            return SourceAudio(wav_path=wav, cache_key=key, origin=origin)
        downloaded = _download_direct(text, settings, work_dir)
        try:
            exported, trimmed, duration = _export_wav(downloaded, wav, settings, max_seconds)
        finally:
            downloaded.unlink(missing_ok=True)
        return SourceAudio(
            wav_path=exported, cache_key=key, origin=origin, trimmed=trimmed, duration=duration
        )

    raise ValueError(
        f"无法识别的歌曲来源: {text!r}（应为网易云 ID/链接、音频直链或本地音频文件路径）"
    )

