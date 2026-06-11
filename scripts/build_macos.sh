#!/usr/bin/env bash
#
# macOS 打包脚本 — 构建 AI视频转录器 .app
#
# 用法:  bash scripts/build_macos.sh
# 输出:  dist/AI视频转录器.app + dist/ai-transcriber-macos.zip
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
cd "$ROOT"

DIST_DIR="$ROOT/dist"
BUILD_DIR="$ROOT/build"
APP_NAME="AI视频转录器"
ZIP_NAME="ai-transcriber-macos-$(date +%Y%m%d).zip"

echo "🔨 开始构建 macOS 桌面应用..."
echo "   项目根目录: $ROOT"

# ── 1. 确保虚拟环境就绪 ──
if [ ! -f "$ROOT/venv/bin/python" ]; then
    echo "❌ 未找到虚拟环境，请先运行: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt pyinstaller pywebview"
    exit 1
fi

echo ""
echo "📦 步骤 1/4: 安装打包依赖..."
"$ROOT/venv/bin/pip" install -q pyinstaller pywebview

# ── 2. 下载 FFmpeg 静态构建 ──
echo ""
echo "📦 步骤 2/4: 准备 FFmpeg..."

FFMPEG_DIR="$ROOT/ffmpeg_bin"
mkdir -p "$FFMPEG_DIR"

if [ -f "$FFMPEG_DIR/ffmpeg" ]; then
    echo "   FFmpeg 已存在，跳过下载"
else
    echo "   下载 FFmpeg 静态构建 (macOS)..."
    # 使用 evermeet.cx 的静态构建
    FFMPEG_URL="https://evermeet.cx/ffmpeg/getrelease/zip"
    TMP_ZIP="/tmp/ffmpeg_macos.zip"
    curl -L -o "$TMP_ZIP" "$FFMPEG_URL" 2>/dev/null || {
        echo "   ⚠️  下载失败，尝试从 Homebrew 复制..."
        if command -v ffmpeg &>/dev/null; then
            cp "$(which ffmpeg)" "$FFMPEG_DIR/ffmpeg"
            chmod +x "$FFMPEG_DIR/ffmpeg"
        else
            echo "   ❌ 无法获取 FFmpeg，请手动放置到 $FFMPEG_DIR/ffmpeg"
            exit 1
        fi
    }
    if [ -f "$TMP_ZIP" ]; then
        unzip -o "$TMP_ZIP" -d "$FFMPEG_DIR" 2>/dev/null
        chmod +x "$FFMPEG_DIR/ffmpeg" 2>/dev/null || true
        rm -f "$TMP_ZIP"
    fi
fi

if [ -f "$FFMPEG_DIR/ffmpeg" ]; then
    echo "   ✅ FFmpeg 就绪: $FFMPEG_DIR/ffmpeg"
else
    echo "   ⚠️  FFmpeg 二进制未找到，应用启动时会尝试使用系统 FFmpeg"
fi

# ── 3. PyInstaller 打包 ──
echo ""
echo "📦 步骤 3/4: PyInstaller 打包..."

# 清理旧的构建产物
rm -rf "$DIST_DIR/$APP_NAME" "$BUILD_DIR/$APP_NAME"

"$ROOT/venv/bin/pyinstaller" \
    --distpath "$DIST_DIR" \
    --workpath "$BUILD_DIR" \
    --noconfirm \
    --clean \
    "$ROOT/pyinstaller/ai_transcriber.spec"

# PyInstaller 输出: dist/AI视频转录器.app (macOS BUNDLE)
# 或 dist/AI视频转录器/ (COLLECT)

# ── 4. 复制 FFmpeg 到应用包 ──
echo ""
echo "📦 步骤 4/4: 复制 FFmpeg 到应用包..."

if [ -d "$DIST_DIR/$APP_NAME.app" ]; then
    # macOS .app bundle
    MACOS_DIR="$DIST_DIR/$APP_NAME.app/Contents/MacOS"
    if [ -f "$FFMPEG_DIR/ffmpeg" ]; then
        cp "$FFMPEG_DIR/ffmpeg" "$MACOS_DIR/ffmpeg"
        chmod +x "$MACOS_DIR/ffmpeg"
        echo "   ✅ FFmpeg 已复制到 .app/Contents/MacOS/"
    fi
    # 也复制 .env 示例
    if [ -f "$ROOT/.env.example" ]; then
        cp "$ROOT/.env.example" "$MACOS_DIR/.env.example"
    fi
elif [ -d "$DIST_DIR/$APP_NAME" ]; then
    # onedir 模式
    if [ -f "$FFMPEG_DIR/ffmpeg" ]; then
        cp "$FFMPEG_DIR/ffmpeg" "$DIST_DIR/$APP_NAME/ffmpeg"
        chmod +x "$DIST_DIR/$APP_NAME/ffmpeg"
        echo "   ✅ FFmpeg 已复制到 $DIST_DIR/$APP_NAME/"
    fi
    if [ -f "$ROOT/.env.example" ]; then
        cp "$ROOT/.env.example" "$DIST_DIR/$APP_NAME/.env.example"
    fi
fi

# ── 5. 打包为 ZIP 发布 ──
echo ""
echo "📦 创建发布包..."

if [ -d "$DIST_DIR/$APP_NAME.app" ]; then
    cd "$DIST_DIR"
    zip -qr "$ZIP_NAME" "$APP_NAME.app"
    echo "   ✅ 发布包: $DIST_DIR/$ZIP_NAME"
elif [ -d "$DIST_DIR/$APP_NAME" ]; then
    cd "$DIST_DIR"
    zip -qr "$ZIP_NAME" "$APP_NAME"
    echo "   ✅ 发布包: $DIST_DIR/$ZIP_NAME"
fi

echo ""
echo "🎉 构建完成!"
echo "   输出位置: $DIST_DIR"
ls -lh "$DIST_DIR"/*.zip 2>/dev/null || ls -lh "$DIST_DIR" | head -20
