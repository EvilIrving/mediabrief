#!/usr/bin/env bash
#
# macOS 打包脚本 — 构建 MediaBrief .app
#
# 用法:  bash scripts/build_macos.sh
# 输出:  dist/MediaBrief.app
# 正式分发物（签名公证后的 DMG）由 scripts/release_macos.sh 生成。
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
cd "$ROOT"

DIST_DIR="${DIST_DIR:-$ROOT/dist}"
BUILD_DIR="${BUILD_DIR:-$ROOT/build}"
APP_NAME="MediaBrief"
VERSION_FILE="$ROOT/VERSION"
[ -f "$VERSION_FILE" ] || { echo "❌ 缺少版本文件: $VERSION_FILE"; exit 1; }
APP_VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
[[ "$APP_VERSION" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || {
    echo "❌ VERSION 格式无效: $APP_VERSION"
    exit 1
}
RELEASE_CONFIG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mediabrief-release-config.XXXXXX")"
RELEASE_CONFIG_PATH="$RELEASE_CONFIG_DIR/release-config.json"
export MEDIABRIEF_RELEASE_CONFIG_PATH="$RELEASE_CONFIG_PATH"
cleanup_release_config() {
    rm -rf "$RELEASE_CONFIG_DIR"
}
trap cleanup_release_config EXIT

# ── 构建架构 ──
# 仅支持 Apple Silicon (arm64)，不支持 Intel Mac。
# mlx / mlx-metal 是 Apple Silicon 专用（Metal 后端），无 universal2 wheel，须在 arm64 机器上构建。
ARCH="$(uname -m)"
if [ "$ARCH" != "arm64" ]; then
    echo "❌ 本应用仅支持 Apple Silicon (arm64)，当前架构: $ARCH"
    exit 1
fi
echo "🔨 开始构建 macOS 桌面应用 (arm64)..."
echo "   版本: $APP_VERSION"
echo "   项目根目录: $ROOT"

# ── 1. 确保虚拟环境就绪 ──
if [ ! -f "$ROOT/venv/bin/python" ]; then
    echo "❌ 未找到虚拟环境，请先运行: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt pyinstaller pywebview"
    exit 1
fi

# 正式发行版内置 AI 配置。优先使用环境变量；否则读取被 Git 忽略、权限为 600
# 的 release-config.json。最终只写入临时构建文件和 .app，不打印凭据。
LOCAL_RELEASE_CONFIG="$ROOT/release-config.json"
if [ -z "${MEDIABRIEF_LLM_API_KEY:-}" ] || [ -z "${MEDIABRIEF_LLM_MODEL:-}" ]; then
    [ -f "$LOCAL_RELEASE_CONFIG" ] || {
        echo "❌ 缺少发行 AI 配置：请设置 MEDIABRIEF_LLM_API_KEY/MODEL 或创建 release-config.json"
        exit 1
    }
    eval "$(RELEASE_CONFIG_SOURCE="$LOCAL_RELEASE_CONFIG" "$ROOT/venv/bin/python" - <<'PY'
import json
import os
import shlex
from pathlib import Path

data = json.loads(Path(os.environ["RELEASE_CONFIG_SOURCE"]).read_text(encoding="utf-8"))
for env_name, key in (
    ("MEDIABRIEF_LLM_API_KEY", "api_key"),
    ("MEDIABRIEF_LLM_BASE_URL", "base_url"),
    ("MEDIABRIEF_LLM_MODEL", "model"),
):
    print(f"{env_name}={shlex.quote(str(data.get(key) or ''))}")
PY
)"
fi
: "${MEDIABRIEF_LLM_API_KEY:?发行配置缺少 api_key}"
: "${MEDIABRIEF_LLM_MODEL:?发行配置缺少 model}"
mkdir -p "$BUILD_DIR"
RELEASE_CONFIG_PATH="$RELEASE_CONFIG_PATH" \
MEDIABRIEF_LLM_API_KEY="$MEDIABRIEF_LLM_API_KEY" \
MEDIABRIEF_LLM_BASE_URL="${MEDIABRIEF_LLM_BASE_URL:-}" \
MEDIABRIEF_LLM_MODEL="$MEDIABRIEF_LLM_MODEL" \
"$ROOT/venv/bin/python" - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["RELEASE_CONFIG_PATH"])
path.write_text(json.dumps({
    "api_key": os.environ["MEDIABRIEF_LLM_API_KEY"],
    "base_url": os.environ.get("MEDIABRIEF_LLM_BASE_URL", ""),
    "model": os.environ["MEDIABRIEF_LLM_MODEL"],
}), encoding="utf-8")
path.chmod(0o600)
PY
echo "   ✅ 发行版 AI 配置已注入（凭据未输出）"

echo ""
echo "📦 步骤 1/4: 安装打包依赖..."
"$ROOT/venv/bin/python" -m pip install -q pyinstaller pywebview
# 始终把 yt-dlp 升到最新 stable 再打包：随包冻结的版本越新越好，
# 运行时还有 yt_dlp_updater 做后续的周度自更新兜底。
echo "   升级 yt-dlp 到最新 stable..."
"$ROOT/venv/bin/python" -m pip install -q --upgrade yt-dlp

# ── 2. 检查 FFmpeg 静态二进制 ──
echo ""
echo "📦 步骤 2/4: 检查 FFmpeg..."

FFMPEG_DIR="$ROOT/ffmpeg_bin"
mkdir -p "$FFMPEG_DIR"

FFMPEG_BIN="$FFMPEG_DIR/ffmpeg-arm64"

# 校验二进制确为 arm64
_ffmpeg_arch_ok() {
    [ -f "$1" ] || return 1
    lipo -archs "$1" 2>/dev/null | tr ' ' '\n' | grep -qx "arm64"
}

FFPROBE_BIN="$FFMPEG_DIR/ffprobe-arm64"

if _ffmpeg_arch_ok "$FFMPEG_BIN" && _ffmpeg_arch_ok "$FFPROBE_BIN"; then
    # 确保不依赖 Homebrew dylib（拒绝动态链接版本）
    if otool -L "$FFMPEG_BIN" "$FFPROBE_BIN" 2>/dev/null | grep -q '/opt/homebrew\|/usr/local/Cellar'; then
        echo "   ❌ FFmpeg/FFprobe 是动态链接版本，无法分发到其他 Mac"
        echo "      请运行: bash scripts/build_ffmpeg.sh"
        exit 1
    fi
    echo "   ✅ FFmpeg/FFprobe arm64 静态二进制就绪"
else
    echo "   ❌ 未找到 arm64 静态 FFmpeg/FFprobe"
    echo "      请先运行: bash scripts/build_ffmpeg.sh"
    exit 1
fi

# ── 3. PyInstaller 打包 ──
echo ""
echo "🎨 步骤 3/5: 生成 .icns 图标..."

ICONSET_DIR="$ROOT/build/icon.iconset"
mkdir -p "$ICONSET_DIR"

# Dedicated macOS app icon (copper tile + baked rounded corners).
# Do not reuse the web favicon: icon_light.svg is a cream square and
# shows up as a sharp rectangle in the DMG / Finder preview.
SVG_SRC="$ROOT/pyinstaller/icon.svg"
SVG_SMALL="$ROOT/pyinstaller/icon-small.svg"
ICNS_OUT="$ROOT/pyinstaller/icon.icns"
mkdir -p "$(dirname "$ICNS_OUT")"

# Punch transparent rounded corners. qlmanage often flattens SVG onto
# an opaque square; this mask is what actually makes the installer icon
# look like a macOS app tile instead of a box.
_apply_round_mask() {
    local png="$1"
    # Optional safety net. rsvg-convert already keeps the SVG clip-path
    # alpha; this only matters when qlmanage flattened the SVG onto white.
    "$ROOT/venv/bin/python" - "$png" <<'PY' || true
import sys
try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit(0)

path = sys.argv[1]
im = Image.open(path).convert("RGBA")
w, h = im.size
radius = max(1, round(min(w, h) * 224 / 1024))
mask = Image.new("L", (w, h), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
im.putalpha(mask)
im.save(path, "PNG")
PY
}

_render_svg() {
    local src="$1" px="$2" dest="$3"
    if command -v rsvg-convert &>/dev/null; then
        rsvg-convert -w "$px" -h "$px" "$src" -o "$dest"
    else
        sips -z "$px" "$px" "$src" --out "$dest" >/dev/null
    fi
    _apply_round_mask "$dest"
}

_svg_for_size() {
    # 16 / 32 / 64: simplified waveform-only mark. 128+: full brand mark.
    local px="$1"
    if [ "$px" -le 64 ]; then
        echo "$SVG_SMALL"
    else
        echo "$SVG_SRC"
    fi
}

_build_icns_from_masters() {
    local master_large="$1" master_small="$2"
    _apply_round_mask "$master_large"
    [ "$master_small" != "$master_large" ] && _apply_round_mask "$master_small"
    for size in 16 32 128 256 512; do
        local src="$master_large"
        [ "$size" -le 32 ] && src="$master_small"
        sips -z "$size" "$size" "$src" --out "$ICONSET_DIR/icon_${size}x${size}.png" >/dev/null
        local src2x="$master_large"
        [ "$((size * 2))" -le 64 ] && src2x="$master_small"
        sips -z $((size * 2)) $((size * 2)) "$src2x" --out "$ICONSET_DIR/icon_${size}x${size}@2x.png" >/dev/null
    done
    cp "$master_large" "$ICONSET_DIR/icon_512x512@2x.png"
    iconutil -c icns "$ICONSET_DIR" -o "$ICNS_OUT"
}

if command -v rsvg-convert &>/dev/null; then
    for size in 16 32 128 256 512; do
        _render_svg "$(_svg_for_size "$size")" "$size" "$ICONSET_DIR/icon_${size}x${size}.png"
        _render_svg "$(_svg_for_size $((size * 2)))" $((size * 2)) "$ICONSET_DIR/icon_${size}x${size}@2x.png"
    done
    _render_svg "$SVG_SRC" 1024 "$ICONSET_DIR/icon_512x512@2x.png"
    iconutil -c icns "$ICONSET_DIR" -o "$ICNS_OUT"
    echo "   ✅ icon.icns 已生成 (rsvg-convert)"
elif command -v qlmanage &>/dev/null; then
    # macOS built-in: render SVG via Quick Look, then resize with sips
    TMP_QLDIR="/tmp/mediabrief_icon_$$"
    mkdir -p "$TMP_QLDIR"
    qlmanage -t -s 1024 -o "$TMP_QLDIR" "$SVG_SRC" "$SVG_SMALL" 2>/dev/null || true
    MASTER_LARGE=$(find "$TMP_QLDIR" -name "icon.svg.png" | head -1)
    MASTER_SMALL=$(find "$TMP_QLDIR" -name "icon-small.svg.png" | head -1)
    if [ -n "$MASTER_LARGE" ] && [ -n "$MASTER_SMALL" ]; then
        _build_icns_from_masters "$MASTER_LARGE" "$MASTER_SMALL"
        rm -rf "$TMP_QLDIR"
        echo "   ✅ icon.icns 已生成 (qlmanage+sips)"
    elif [ -n "$MASTER_LARGE" ]; then
        _build_icns_from_masters "$MASTER_LARGE" "$MASTER_LARGE"
        rm -rf "$TMP_QLDIR"
        echo "   ✅ icon.icns 已生成 (qlmanage+sips, 无小尺寸稿)"
    else
        rm -rf "$TMP_QLDIR"
        echo "   ⚠️  qlmanage 渲染失败，跳过图标生成 (brew install librsvg 可修复)"
    fi
else
    echo "   ⚠️  跳过图标生成，请安装 rsvg-convert: brew install librsvg"
fi

echo ""
echo "📦 步骤 4/5: PyInstaller 打包 (one-dir + 原生 .app BUNDLE)..."

# 清理旧的构建产物和不应进入 dist 的中间包
rm -rf "$DIST_DIR/$APP_NAME" "$DIST_DIR/$APP_NAME.app" "$DIST_DIR/mediabrief" "$DIST_DIR/ai-transcriber" "$BUILD_DIR/$APP_NAME"
rm -rf "$DIST_DIR"/MediaBrief.app.stale-*
rm -f "$DIST_DIR"/MediaBrief-*-macos-arm64.zip \
    "$DIST_DIR"/MediaBrief-*-notary.zip \
    "$DIST_DIR"/mediabrief-macos-*.zip \
    "$DIST_DIR"/notary-*.json \
    "$DIST_DIR"/notarize-*.log \
    "$DIST_DIR"/sign-*.log

"$ROOT/venv/bin/python" -m PyInstaller \
    --distpath "$DIST_DIR" \
    --workpath "$BUILD_DIR" \
    --noconfirm \
    --clean \
    "$ROOT/pyinstaller/ai_transcriber.spec"

# PyInstaller BUNDLE 直接输出: dist/MediaBrief.app（含 .icns + Info.plist）

echo ""
echo "📦 步骤 5/5: 注入 FFmpeg..."

APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
MACOS_DIR="$APP_BUNDLE/Contents/MacOS"

if [ ! -d "$APP_BUNDLE" ]; then
    echo "❌ PyInstaller 未生成 $APP_BUNDLE"
    exit 1
fi

# start.py 通过 sys.executable.parent (= Contents/MacOS) 查找 ffmpeg。
# 模型/API 配置由前端设置页持久化，不在安装包中注入环境变量模板。
if [ -f "$FFMPEG_BIN" ]; then
    cp "$FFMPEG_BIN" "$MACOS_DIR/ffmpeg"
    chmod +x "$MACOS_DIR/ffmpeg"
    echo "   ✅ FFmpeg ($ARCH) 已注入 .app/Contents/MacOS/"
fi
# ffprobe：时长校验/重封装依赖；缺失会让校验静默失效。
if [ -f "$FFPROBE_BIN" ]; then
    cp "$FFPROBE_BIN" "$MACOS_DIR/ffprobe"
    chmod +x "$MACOS_DIR/ffprobe"
    echo "   ✅ FFprobe ($ARCH) 已注入 .app/Contents/MacOS/"
fi

# ── 注入 Deno（YouTube nsig 签名解算所需的 JS 运行时） ──
# 缺失时 YouTube 下载/转录会报 "Requested format is not available"。
# start.py 通过 sys.executable.parent (= Contents/MacOS) 查找并注入 PATH。
DENO_BIN="$ROOT/deno_bin/deno"
if [ ! -x "$DENO_BIN" ]; then
    echo "   ⬇️  未找到 Deno，自动下载..."
    bash "$ROOT/scripts/fetch_deno.sh"
fi
if [ -f "$DENO_BIN" ]; then
    cp "$DENO_BIN" "$MACOS_DIR/deno"
    chmod +x "$MACOS_DIR/deno"
    echo "   ✅ Deno 已注入 .app/Contents/MacOS/"
else
    echo "   ❌ Deno 注入失败，拒绝生成 YouTube 支持不完整的发行包"
    exit 1
fi

echo "   ✅ .app Bundle 就绪: $APP_BUNDLE"
# COLLECT 的 one-dir 目录只是 BUNDLE 的中间副本，不作为产物留下。
rm -rf "$DIST_DIR/$APP_NAME"

# ── 校验 mlx Metal 后端资产已收进 bundle ──
# MLX 的 Metal 后端是独立发行包：缺 mlx.metallib 或 libmlx.dylib 时，打包后会在
# 首次转录时崩/退回不可用。这里做一次存在性 + 链接体检（非致命，只告警）。
echo ""
echo "🔎 校验 mlx Metal 后端资产..."
RES_DIR="$APP_BUNDLE/Contents/Resources"
FRAMEWORKS_DIR="$APP_BUNDLE/Contents/Frameworks"
_metallib=$(find "$RES_DIR" "$FRAMEWORKS_DIR" -name "mlx.metallib" 2>/dev/null | head -1)
_libmlx=$(find "$RES_DIR" "$FRAMEWORKS_DIR" -name "libmlx.dylib" 2>/dev/null | head -1)
_mlxcore=$(find "$RES_DIR" "$FRAMEWORKS_DIR" -name "core.cpython-*-darwin.so" -path "*mlx*" 2>/dev/null | head -1)
if [ -n "$_metallib" ]; then echo "   ✅ mlx.metallib: $_metallib"; else echo "   ❌ 未找到 mlx.metallib —— 拒绝生成无法 GPU 转录的发行包"; exit 1; fi
if [ -n "$_libmlx" ]; then echo "   ✅ libmlx.dylib: $_libmlx"; else echo "   ❌ 未找到 libmlx.dylib"; exit 1; fi
if [ -z "$_mlxcore" ]; then echo "   ❌ 未找到 mlx core 原生模块"; exit 1; fi
if [ -n "$_mlxcore" ]; then
    echo "   mlx core 动态库链接 (otool -L):"
    otool -L "$_mlxcore" 2>/dev/null | sed -n '2,12p' | sed 's/^/      /'
fi
echo "   ✅ MLX Metal 运行资产完整"

echo ""
echo "🎉 构建完成!"
echo "   输出: $APP_BUNDLE"
