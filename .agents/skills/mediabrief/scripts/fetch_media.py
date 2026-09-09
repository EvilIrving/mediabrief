#!/usr/bin/env python3
"""Download audio (and optional video) plus subtitles for the MediaBrief skill."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def _which_or_die(name: str) -> str:
    path = shutil.which(name)
    if not path:
        sys.stderr.write(f"missing dependency: {name}\n")
        sys.exit(2)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--video", action="store_true", help="also download video")
    parser.add_argument("--cookies-from-browser", dest="cookies_browser", default="")
    args = parser.parse_args()

    yt = _which_or_die("yt-dlp")
    _which_or_die("ffmpeg")

    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    tmpl = str(out / "%(title).80B-%(id)s.%(ext)s")

    cmd = [
        yt,
        "--no-playlist",
        "--newline",
        "-o",
        tmpl,
        "--write-info-json",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        "en.*,zh.*,ja.*,ko.*,all",
        "--convert-subs",
        "vtt",
        "--print",
        "after_move:filepath",
    ]
    if args.cookies_browser:
        cmd.extend(["--cookies-from-browser", args.cookies_browser])
    if args.video:
        cmd.extend(["-f", "bv*+ba/b"])
    else:
        cmd.extend(["-f", "ba/b", "-x", "--audio-format", "m4a"])
    cmd.append(args.url)

    proc = subprocess.run(cmd, cwd=str(out), text=True)
    if proc.returncode != 0:
        return proc.returncode

    info_files = sorted(out.glob("*.info.json"))
    audio = _first(out, {".m4a", ".mp3", ".opus", ".ogg", ".wav", ".webm", ".flac"})
    video = _first(out, {".mp4", ".mkv", ".webm", ".mov"}) if args.video else None
    subs = sorted(p for p in out.iterdir() if p.suffix.lower() in {".vtt", ".srt"})
    title = ""
    extractor = ""
    if info_files:
        payload = json.loads(info_files[-1].read_text(encoding="utf-8"))
        title = str(payload.get("title") or "")
        extractor = str(payload.get("extractor") or payload.get("ie_key") or "")

    source = {
        "url": args.url,
        "title": title,
        "extractor": extractor,
        "audio": str(audio) if audio else None,
        "video": str(video) if video else None,
        "subtitles": [str(p) for p in subs],
        "mode_hint": "subtitle" if subs else "whisper",
    }
    (out / "source.json").write_text(
        json.dumps(source, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(source, ensure_ascii=False))
    return 0


def _first(folder: Path, suffixes: set[str]) -> Path | None:
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() in suffixes and path.name.endswith(".info.json") is False:
            if path.suffix.lower() == ".webm" and any(
                p.suffix.lower() in {".m4a", ".mp3"} for p in folder.iterdir()
            ):
                continue
            return path
    return None


if __name__ == "__main__":
    raise SystemExit(main())
