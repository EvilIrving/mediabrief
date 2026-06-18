#!/usr/bin/env bash
#
# macOS 打包脚本 — 构建 MediaBrief .app
#
# 用法:  bash scripts/build_macos.sh
# 输出:  dist/MediaBrief.app + dist/mediabrief-macos.zip
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
cd "$ROOT"

DIST_DIR="$ROOT/dist"
BUILD_DIR="$ROOT/build"
APP_NAME="MediaBrief"

# ── 构建架构 ──
# 仅支持 Apple Silicon (arm64)，不支持 Intel Mac。
# ctranslate2 等依赖只有单架构 wheel，无法构建 universal2，须在 arm64 机器上构建。
ARCH="$(uname -m)"
if [ "$ARCH" != "arm64" ]; then
    echo "❌ 本应用仅支持 Apple Silicon (arm64)，当前架构: $ARCH"
    exit 1
fi
ZIP_NAME="mediabrief-macos-arm64-$(date +%Y%m%d).zip"

echo "🔨 开始构建 macOS 桌面应用 (arm64)..."
echo "   项目根目录: $ROOT"

# ── 1. 确保虚拟环境就绪 ──
if [ ! -f "$ROOT/venv/bin/python" ]; then
    echo "❌ 未找到虚拟环境，请先运行: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt pyinstaller pywebview"
    exit 1
fi

echo ""
echo "📦 步骤 1/4: 安装打包依赖..."
"$ROOT/venv/bin/pip" install -q pyinstaller pywebview
# 始终把 yt-dlp 升到最新 stable 再打包：随包冻结的版本越新越好，
# 运行时还有 yt_dlp_updater 做后续的周度自更新兜底。
echo "   升级 yt-dlp 到最新 stable..."
"$ROOT/venv/bin/pip" install -q --upgrade yt-dlp

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

SVG_SRC="$ROOT/frontend/public/icon_light.svg"
ICNS_OUT="$ROOT/pyinstaller/icon.icns"
mkdir -p "$(dirname "$ICNS_OUT")"

_build_icns_from_png() {
    local src_png="$1"
    for size in 16 32 128 256 512; do
        sips -z $size $size "$src_png" --out "$ICONSET_DIR/icon_${size}x${size}.png" >/dev/null
        sips -z $((size*2)) $((size*2)) "$src_png" --out "$ICONSET_DIR/icon_${size}x${size}@2x.png" >/dev/null
    done
    cp "$src_png" "$ICONSET_DIR/icon_512x512@2x.png"
    iconutil -c icns "$ICONSET_DIR" -o "$ICNS_OUT"
}

if command -v rsvg-convert &>/dev/null; then
    for size in 16 32 128 256 512; do
        rsvg-convert -w $size -h $size "$SVG_SRC" -o "$ICONSET_DIR/icon_${size}x${size}.png"
        rsvg-convert -w $((size*2)) -h $((size*2)) "$SVG_SRC" -o "$ICONSET_DIR/icon_${size}x${size}@2x.png"
    done
    rsvg-convert -w 1024 -h 1024 "$SVG_SRC" -o "$ICONSET_DIR/icon_512x512@2x.png"
    iconutil -c icns "$ICONSET_DIR" -o "$ICNS_OUT"
    echo "   ✅ icon.icns 已生成 (rsvg-convert)"
elif command -v qlmanage &>/dev/null; then
    # macOS built-in: render SVG via Quick Look, then resize with sips
    TMP_QLDIR="/tmp/ai_transcriber_icon_$$"
    mkdir -p "$TMP_QLDIR"
    qlmanage -t -s 1024 -o "$TMP_QLDIR" "$SVG_SRC" 2>/dev/null || true
    TMP_PNG=$(find "$TMP_QLDIR" -name "*.png" | head -1)
    if [ -n "$TMP_PNG" ]; then
        _build_icns_from_png "$TMP_PNG"
        rm -rf "$TMP_QLDIR"
        echo "   ✅ icon.icns 已生成 (qlmanage+sips)"
    else
        rm -rf "$TMP_QLDIR"
        echo "   ⚠️  qlmanage 渲染失败，跳过图标生成 (brew install librsvg 可修复)"
    fi
else
    echo "   ⚠️  跳过图标生成，请安装 rsvg-convert: brew install librsvg"
fi

echo ""
echo "📦 步骤 4/5: PyInstaller 打包 (one-dir + 原生 .app BUNDLE)..."

# 清理旧的构建产物
rm -rf "$DIST_DIR/$APP_NAME" "$DIST_DIR/$APP_NAME.app" "$DIST_DIR/mediabrief" "$DIST_DIR/ai-transcriber" "$BUILD_DIR/$APP_NAME"

"$ROOT/venv/bin/pyinstaller" \
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
    echo "   ⚠️  Deno 注入失败，打包后 YouTube 签名解算可能不可用"
fi

echo "   ✅ .app Bundle 就绪: $APP_BUNDLE"

# ── 打包为 ZIP 发布 ──
# 使用 ditto 而非 zip：保留 PyInstaller .app 内的符号链接与权限位，
# 否则解压后应用可能无法启动 / 公证失败。
echo ""
echo "📦 创建发布包..."

ditto -c -k --keepParent "$APP_BUNDLE" "$DIST_DIR/$ZIP_NAME"
echo "   ✅ 发布包: $DIST_DIR/$ZIP_NAME"

echo ""
echo "🎉 构建完成!"
echo "   输出位置: $DIST_DIR"
ls -lh "$DIST_DIR"/*.zip 2>/dev/null || ls -lh "$DIST_DIR" | head -20
