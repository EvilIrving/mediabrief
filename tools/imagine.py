#!/usr/bin/env python3
"""Call Grok Imagine with the local Grok Build session token.

Examples:
  tools/imagine.py "黄昏窗边的木桌和耳机"
  tools/imagine.py photo.jpg "改成油画风格"
  tools/imagine.py a.jpg b.jpg "把两个人放在同一张长椅上"
  tools/imagine.py generate --ratio 16:9 --out out.jpg "一只橘猫"
  tools/imagine.py edit --image photo.jpg --out out.jpg "暖色电影光"
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MODEL = "grok-imagine-image-2.0"
DEFAULT_BASE = "https://api.x.ai/v1"
AUTH_PATH = Path.home() / ".grok" / "auth.json"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


def die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def load_token() -> tuple[str, str]:
    if AUTH_PATH.exists():
        try:
            data = json.loads(AUTH_PATH.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            die(f"无法读取 {AUTH_PATH}: {exc}")
        if isinstance(data, dict) and data:
            entry = next(iter(data.values()))
            if isinstance(entry, dict):
                key = (entry.get("key") or "").strip()
                if key:
                    expires_at = entry.get("expires_at")
                    if expires_at:
                        try:
                            exp = datetime.fromisoformat(
                                str(expires_at).replace("Z", "+00:00")
                            )
                            left = (exp - datetime.now(timezone.utc)).total_seconds()
                            if left <= 0:
                                die("Grok session 已过期，请先运行 `grok login`")
                            if left < 300:
                                print("警告: Grok session 将在 5 分钟内过期", file=sys.stderr)
                        except ValueError:
                            pass
                    return key, "grok-session"

    for env_name in ("XAI_API_KEY", "GROK_CODE_XAI_API_KEY"):
        value = (os.environ.get(env_name) or "").strip()
        if value:
            return value, env_name

    die("没有可用 token。先 `grok login`，或设置 XAI_API_KEY")


def sniff_mime(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed and guessed.startswith("image/"):
        return guessed
    return "image/jpeg"


def image_ref(value: str) -> dict:
    raw = value.strip()
    if raw.startswith(("http://", "https://", "data:")):
        return {"type": "image_url", "url": raw}

    path = Path(raw).expanduser()
    if not path.is_file():
        die(f"找不到图片: {value}")
    blob = path.read_bytes()
    if not blob:
        die(f"空文件: {path}")
    mime = sniff_mime(path)
    encoded = base64.b64encode(blob).decode("ascii")
    return {"type": "image_url", "url": f"data:{mime};base64,{encoded}"}


def looks_like_image_arg(value: str) -> bool:
    raw = value.strip()
    if raw.startswith(("http://", "https://", "data:image/")):
        return True
    return Path(raw).expanduser().suffix.lower() in IMAGE_EXTS


def default_out_path(prefix: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path("artifacts")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{prefix}-{stamp}.jpg"


def resolve_out(out: str | None, prefix: str) -> Path:
    if not out:
        return default_out_path(prefix)
    path = Path(out).expanduser()
    if path.exists() and path.is_dir():
        return path / default_out_path(prefix).name
    if str(out).endswith(("/", os.sep)):
        path.mkdir(parents=True, exist_ok=True)
        return path / default_out_path(prefix).name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def post_json(url: str, token: str, payload: dict, timeout: int) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        detail = detail.replace(token, "<redacted>")
        die(f"HTTP {exc.code} {exc.reason}\n{detail[:2000]}", 1)
    except urllib.error.URLError as exc:
        die(f"请求失败: {exc.reason}", 1)

    if status != 200:
        die(f"HTTP {status}: {raw[:500]!r}", 1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        die("响应不是 JSON", 1)


def save_images(data: dict, out: Path) -> list[Path]:
    items = data.get("data") or []
    if not items:
        die(f"响应里没有图片: {list(data.keys())}", 1)

    saved: list[Path] = []
    for index, item in enumerate(items):
        dest = out if index == 0 else out.with_name(f"{out.stem}-{index + 1}{out.suffix}")
        if item.get("b64_json"):
            dest.write_bytes(base64.b64decode(item["b64_json"]))
        elif item.get("url"):
            req = urllib.request.Request(item["url"])
            with urllib.request.urlopen(req, timeout=120) as resp:
                dest.write_bytes(resp.read())
        else:
            die(f"图片 {index} 缺少 b64_json / url: {list(item.keys())}", 1)
        saved.append(dest)
    return saved


def build_payload(args: argparse.Namespace, images: list[str], prompt: str) -> dict:
    payload: dict = {
        "model": args.model,
        "prompt": prompt,
        "response_format": "b64_json",
    }
    if args.n != 1:
        payload["n"] = args.n
    if args.ratio:
        payload["aspect_ratio"] = args.ratio
    if args.resolution:
        payload["resolution"] = args.resolution
    if args.quality:
        payload["quality"] = args.quality
    if len(images) == 1:
        payload["image"] = image_ref(images[0])
    elif len(images) > 1:
        payload["images"] = [image_ref(item) for item in images]
    return payload


def run(args: argparse.Namespace) -> int:
    images = list(args.images or [])
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        die("请提供提示词")
    if args.command == "edit" and not images:
        die("edit 需要至少一张图片：--image PATH 或位置参数")
    if args.command == "generate" and images:
        die("generate 不接受图片，请用 edit")
    if len(images) > 3:
        die("最多上传 3 张参考图")

    token, source = load_token()
    mode = "edit" if images else "generate"
    path = "/images/edits" if images else "/images/generations"
    url = args.base.rstrip("/") + path
    payload = build_payload(args, images, prompt)
    out = resolve_out(args.out, f"imagine-{mode}")

    print(f"auth={source}  model={args.model}  mode={mode}")
    if images:
        print("images=" + ", ".join(images))
    print(f"prompt={prompt}")

    started = time.time()
    data = post_json(url, token, payload, timeout=args.timeout)
    elapsed = time.time() - started
    saved = save_images(data, out)

    usage = data.get("usage") or {}
    extra = f"  usage={usage}" if usage else ""
    print(f"ok  {elapsed:.1f}s{extra}")
    for path in saved:
        print(path.resolve())
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="imagine.py",
        description="用 Grok Build 登录态调用 Imagine：文生图，或上传图片改图。",
        epilog=(
            "例子:\n"
            "  tools/imagine.py 黄昏窗边的木桌\n"
            "  tools/imagine.py photo.jpg 改成油画风格\n"
            "  tools/imagine.py --image a.jpg --image b.jpg 把两人放到同一张长椅上\n"
            "  tools/imagine.py generate --ratio 16:9 一只橘猫\n"
            "  tools/imagine.py edit photo.jpg 暖色电影光"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base", default=os.environ.get("XAI_API_BASE", DEFAULT_BASE))
    parser.add_argument("--ratio", dest="ratio", default=None, help="如 1:1 / 16:9 / auto")
    parser.add_argument("--resolution", default=None, choices=("1k", "2k"))
    parser.add_argument("--quality", default=None, choices=("low", "medium"))
    parser.add_argument("-n", type=int, default=1, help="一次生成几张，默认 1")
    parser.add_argument("--out", default=None, help="输出文件或目录")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--image",
        action="append",
        dest="flag_images",
        default=[],
        help="参考图，可重复，最多 3 张。也可直接把图片路径放在提示词前面",
    )
    parser.add_argument("tokens", nargs="*", help="可选的 generate/edit，然后是图片路径和提示词")
    args = parser.parse_args(argv)

    tokens = list(args.tokens)
    command = None
    if tokens and tokens[0] in {"generate", "edit"}:
        command = tokens.pop(0)

    images: list[str] = list(args.flag_images)
    while tokens and looks_like_image_arg(tokens[0]):
        images.append(tokens.pop(0))

    if command == "generate" and images:
        die("generate 不接受图片，请去掉图片路径或改用 edit")
    if command == "edit" and not images:
        die("edit 需要至少一张图片")

    args.images = images
    args.prompt = tokens
    args.command = command or ("edit" if images else "generate")
    if not args.prompt:
        parser.print_help()
        raise SystemExit(2)
    return args


if __name__ == "__main__":
    sys.exit(run(parse_args(sys.argv[1:])))
