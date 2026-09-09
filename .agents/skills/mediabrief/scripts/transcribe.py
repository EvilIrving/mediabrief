#!/usr/bin/env python3
"""Transcribe audio with mlx-whisper or faster-whisper."""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio")
    parser.add_argument("--out", required=True)
    parser.add_argument("--language", default="")
    parser.add_argument("--model", default="mlx-community/whisper-small-mlx")
    args = parser.parse_args()

    audio = Path(args.audio).expanduser().resolve()
    if not audio.is_file():
        sys.stderr.write(f"audio not found: {audio}\n")
        return 2

    kwargs = {}
    if args.language:
        kwargs["language"] = args.language

    text = _transcribe_mlx(str(audio), args.model, kwargs)
    if text is None:
        text = _transcribe_faster(str(audio), kwargs)
    if text is None:
        sys.stderr.write(
            "install mlx-whisper (Apple Silicon) or faster-whisper before transcribing\n"
        )
        return 2

    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text.strip() + "\n", encoding="utf-8")
    print(out)
    return 0


def _transcribe_mlx(audio: str, model: str, kwargs: dict) -> str | None:
    try:
        mlx_whisper = importlib.import_module("mlx_whisper")
    except Exception:
        return None
    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=model,
        verbose=False,
        **kwargs,
    )
    return str(result.get("text") or "")


def _transcribe_faster(audio: str, kwargs: dict) -> str | None:
    try:
        from faster_whisper import WhisperModel
    except Exception:
        return None
    model_id = "small"
    model = WhisperModel(model_id, device="auto")
    segments, _info = model.transcribe(audio, **kwargs)
    return "".join(segment.text for segment in segments)


if __name__ == "__main__":
    raise SystemExit(main())
