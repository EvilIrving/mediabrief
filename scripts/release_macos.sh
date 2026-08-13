#!/usr/bin/env bash
# 从当前源码生成可直接分发的签名、公证 Apple Silicon DMG。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
FINAL_DIST="$ROOT/dist"
RELEASE_STAGE=$(mktemp -d "/tmp/mediabrief-release.XXXXXX")
STAGE_DIST="$RELEASE_STAGE/dist"
STAGE_BUILD="$RELEASE_STAGE/build"
SIGNING_STAGE=""

cleanup_release_stages() {
    [ -z "$SIGNING_STAGE" ] || rm -rf "$SIGNING_STAGE"
    rm -rf "$RELEASE_STAGE"
}
trap cleanup_release_stages EXIT

cd "$ROOT"

echo "🚀 MediaBrief $VERSION 正式发行"
echo "📦 构建前端资源..."
CI=true pnpm build

echo "📦 构建内置运行环境的 macOS app..."
DIST_DIR="$STAGE_DIST" BUILD_DIR="$STAGE_BUILD" bash "$ROOT/scripts/build_macos.sh"

echo "🔐 签名、公证、staple 并生成 DMG..."
APP_ZIP="$STAGE_DIST/MediaBrief-${VERSION}-macos-arm64.zip"
[ -f "$APP_ZIP" ] || { echo "❌ 缺少 app 归档: $APP_ZIP"; exit 1; }
SIGNING_STAGE=$(mktemp -d "/tmp/mediabrief-signing.XXXXXX")
ditto -x -k "$APP_ZIP" "$SIGNING_STAGE"
DIST_DIR="$STAGE_DIST" APP_PATH="$SIGNING_STAGE/MediaBrief.app" \
    bash "$ROOT/scripts/sign_and_package.sh" notarize

# 不能把构建阶段的未签名 ZIP 留作发行物；用已签名、公证并 staple 的 app 覆盖它。
rm -f "$APP_ZIP"
ditto -c -k --sequesterRsrc --keepParent "$SIGNING_STAGE/MediaBrief.app" "$APP_ZIP"

DMG="$STAGE_DIST/MediaBrief-${VERSION}-macos-arm64.dmg"
MANIFEST="$STAGE_DIST/MediaBrief-${VERSION}-macos-arm64-manifest.json"
[ -f "$DMG" ] || { echo "❌ 发行命令结束但未找到 $DMG"; exit 1; }
[ -f "$MANIFEST" ] || { echo "❌ 发行命令结束但未找到 $MANIFEST"; exit 1; }

mkdir -p "$FINAL_DIST"
ditto "$DMG" "$FINAL_DIST/$(basename "$DMG")"
ditto "$MANIFEST" "$FINAL_DIST/$(basename "$MANIFEST")"
ditto "$APP_ZIP" "$FINAL_DIST/$(basename "$APP_ZIP")"

echo "✅ 正式发行物: $FINAL_DIST/$(basename "$DMG")"
echo "✅ 发行清单:   $FINAL_DIST/$(basename "$MANIFEST")"
