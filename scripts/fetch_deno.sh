#!/usr/bin/env bash
#
# 下载 Deno 二进制（macOS arm64），供打包注入。
#
# 产物: deno_bin/deno
# 用途: yt-dlp 解 YouTube nsig 签名（EJS 方案）需要 Deno 作为 JS 运行时；
#       终端用户机器通常没有 Deno，缺失时 YouTube 可用 format 会被清空，
#       表现为 "Requested format is not available"。打包时把 Deno 一起分发。
#
# 用法:  bash scripts/fetch_deno.sh [版本号]
#        默认下载最新版；指定版本如 v2.1.4 可固定。
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
cd "$ROOT"

DENO_DIR="$ROOT/deno_bin"
mkdir -p "$DENO_DIR"
DENO_BIN="$DENO_DIR/deno"

VERSION="${1:-latest}"

ARCH="$(uname -m)"
if [ "$ARCH" != "arm64" ]; then
    echo "❌ 本脚本仅支持 Apple Silicon (arm64)，当前架构: $ARCH"
    exit 1
fi

# 已就绪（且版本受支持，>=2.0.0）则跳过
if [ -x "$DENO_BIN" ] && "$DENO_BIN" --version >/dev/null 2>&1; then
    echo "✅ Deno 已就绪: $DENO_BIN ($("$DENO_BIN" --version | head -1))"
    echo "   如需重新下载，请先: rm $DENO_BIN"
    exit 0
fi

ASSET="deno-aarch64-apple-darwin.zip"
if [ "$VERSION" = "latest" ]; then
    URL="https://github.com/denoland/deno/releases/latest/download/$ASSET"
else
    URL="https://github.com/denoland/deno/releases/download/$VERSION/$ASSET"
fi

echo "⬇️  下载 Deno ($VERSION) arm64: $URL"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

curl -fSL "$URL" -o "$TMP/deno.zip"
unzip -q -o "$TMP/deno.zip" -d "$TMP"
mv "$TMP/deno" "$DENO_BIN"
chmod +x "$DENO_BIN"

# 移除隔离属性，避免分发后 Gatekeeper 拦截
xattr -d com.apple.quarantine "$DENO_BIN" 2>/dev/null || true

echo "✅ Deno 就绪: $DENO_BIN ($("$DENO_BIN" --version | head -1))"
