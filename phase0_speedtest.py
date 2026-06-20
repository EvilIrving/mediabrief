#!/usr/bin/env python3
"""Phase 0 测速 spike：测 mlx-whisper large-v3-turbo 在本机的真实转录耗时。

一次性测量用，跑通拿到数字后即可删除。不接入主程序、不改动任何现有代码。

用法：
    1. 把测试音频放到项目根目录，命名 phase0_audio.<ext>
       （phase0_audio.mp3 / .m4a / .wav / .mp4 / .webm 均可，自动识别）
    2. ./venv/bin/python phase0_speedtest.py

输出：音频时长、墙钟转录耗时、实时倍率、检测语言、前若干段文本抽查质量。
首次运行会自动下载 ~1.6GB turbo 权重，计时会包含下载，故下方分别提示。
"""
import glob
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = "mlx-community/whisper-large-v3-turbo"


def find_audio():
    hits = sorted(glob.glob(str(ROOT / "phase0_audio.*")))
    return hits[0] if hits else None


def audio_seconds(path):
    """用 ffprobe 取音频时长（秒）；失败返回 None。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return float(out)
    except Exception:
        return None


def main():
    audio = find_audio()
    if not audio:
        print("❌ 没找到 phase0_audio.* —— 请把测试音频放到项目根目录，"
              "命名 phase0_audio.<ext>（如 phase0_audio.mp3）")
        sys.exit(1)

    print(f"🎧 音频: {audio}")
    dur = audio_seconds(audio)
    if dur:
        print(f"⏱  时长: {dur / 60:.1f} 分钟 ({dur:.0f}s)")

    print(f"🧠 模型: {REPO}")
    print("   首次运行会自动下载 ~1.6GB 权重；为分离下载与解码耗时，"
          "先单独预下载再计时转录。")

    # ── 预下载（与解码计时分离）──
    t_dl = time.monotonic()
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(REPO)
        print(f"📥 模型就绪，下载/校验耗时: {time.monotonic() - t_dl:.0f}s")
    except Exception as e:
        print(f"⚠️  预下载步骤跳过（transcribe 时会自动拉取）: {e}")

    import mlx_whisper

    # ── 真正计时的解码 ──
    t0 = time.monotonic()
    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=REPO,
        no_speech_threshold=0.6,
        compression_ratio_threshold=2.4,
        logprob_threshold=-1.0,
        condition_on_previous_text=False,
        word_timestamps=False,
        verbose=False,
    )
    elapsed = time.monotonic() - t0

    text = result.get("text", "") or ""
    segs = result.get("segments", []) or []
    lang = result.get("language", "?")

    print("\n===== 结果 =====")
    print(f"检测语言: {lang}")
    print(f"墙钟转录耗时: {elapsed / 60:.1f} 分钟 ({elapsed:.0f}s)")
    if dur and elapsed > 0:
        print(f"实时倍率: {dur / elapsed:.1f}×  （音频时长 / 转录耗时，越大越快）")
        print(f"  → 按此倍率，1 小时音频约 {60 / (dur / elapsed):.1f} 分钟")
    print(f"段数: {len(segs)}   总字数: {len(text)}")

    print("\n--- 前 8 段抽查质量 ---")
    for s in segs[:8]:
        print(f"[{s.get('start', 0):.1f}-{s.get('end', 0):.1f}] {s.get('text', '').strip()}")


if __name__ == "__main__":
    main()
