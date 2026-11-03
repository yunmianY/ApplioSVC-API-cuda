"""网易云扫码登录：自动拿 cookie 并写入 config.json（不会把 cookie 打印出来）。

用法：
    python tools/netease_qr_login.py                 # 默认 3 分钟超时
    python tools/netease_qr_login.py --timeout 300
    python tools/netease_qr_login.py --no-save       # 只登录，不写配置

前提：本机已运行 NeteaseCloudMusicApi（默认 http://127.0.0.1:3000）。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import requests  # noqa: E402

from core.settings import CONFIG_PATH, get_settings  # noqa: E402

QR_PNG = PROJECT_DIR / "temp" / "netease_login_qr.png"


def mask(value: str) -> str:
    if not value:
        return "(空)"
    return f"{value[:6]}...{value[-4:]}（长度 {len(value)}）"


def post(path: str, base: str, **params):
    response = requests.get(f"{base}{path}", params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def save_login(cookie: str, base: str) -> None:
    """把清洗后的 cookie 与 API 地址写进 config.json，保留其它字段。"""
    from core.downloader import normalize_cookie

    data = {}
    if CONFIG_PATH.is_file():
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    data["netease_api_base"] = base
    data["netease_cookie"] = normalize_cookie(cookie)
    CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"cookie 已清洗：{len(cookie)} 字符 -> {len(data['netease_cookie'])} 字符"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="网易云扫码登录")
    parser.add_argument("--base", default="", help="NeteaseCloudMusicApi 地址")
    parser.add_argument("--timeout", type=int, default=180, help="等待扫码的秒数")
    parser.add_argument("--no-save", action="store_true", help="不写入 config.json")
    args = parser.parse_args()

    settings = get_settings()
    base = (args.base or settings.netease_api_base or "http://127.0.0.1:3000").rstrip("/")
    print(f"API: {base}")

    try:
        key_resp = post("/login/qr/key", base)
    except Exception as exc:
        print(f"[失败] 连不上接口，服务没启动？{exc}")
        print("       先运行： npx NeteaseCloudMusicApi@4.32.0")
        return 1

    unikey = (key_resp.get("data") or {}).get("unikey")
    if not unikey:
        print(f"[失败] 没拿到 unikey: {key_resp}")
        return 1
    print(f"unikey: {unikey}")

    create = post("/login/qr/create", base, key=unikey, qrimg="true")
    qrimg = (create.get("data") or {}).get("qrimg") or ""
    if not qrimg.startswith("data:image"):
        print(f"[失败] 没拿到二维码图片: {str(create)[:200]}")
        return 1

    payload = qrimg.split(",", 1)[1]
    QR_PNG.parent.mkdir(parents=True, exist_ok=True)
    QR_PNG.write_bytes(base64.b64decode(payload))
    print(f"二维码已保存: {QR_PNG}")
    try:
        os.startfile(str(QR_PNG))  # noqa: S606 - Windows 下用默认看图工具打开
    except Exception:
        print("（自动打开失败，请手动双击上面的图片）")
    print("\n请用手机网易云 App 扫码，并在手机上确认登录…")

    deadline = time.time() + max(30, args.timeout)
    last_code = None
    while time.time() < deadline:
        try:
            check = post("/login/qr/check", base, key=unikey)
        except Exception as exc:
            print(f"  轮询失败（重试中）: {exc}")
            time.sleep(3)
            continue

        code = check.get("code")
        if code != last_code:
            message = {
                800: "二维码已过期，请重新运行本脚本",
                801: "等待扫码…",
                802: "已扫码，请在手机上点击确认",
                803: "登录成功！",
            }.get(code, str(check.get("message") or code))
            print(f"  [{code}] {message}")
            last_code = code

        if code == 803:
            cookie = check.get("cookie") or ""
            if not cookie:
                print("[失败] 登录成功但没返回 cookie")
                return 1
            print(f"\ncookie(原始): {mask(cookie)}")
            if args.no_save:
                print("已按 --no-save 跳过写配置")
            else:
                save_login(cookie, base)
                print(f"已写入 {CONFIG_PATH} 的 netease_cookie / netease_api_base")
                print("下一步：重启中间层，然后运行 tools/check_netease_login.py 验证")
            return 0
        if code == 800:
            return 1
        time.sleep(2)

    print("\n[超时] 没等到扫码确认，请重新运行本脚本")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
