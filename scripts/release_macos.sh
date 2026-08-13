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
cleanup_release_stages() {
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
STAGE_APP="$STAGE_DIST/MediaBrief.app"
[ -d "$STAGE_APP" ] || { echo "❌ 缺少 $STAGE_APP"; exit 1; }
DIST_DIR="$STAGE_DIST" APP_PATH="$STAGE_APP" \
    bash "$ROOT/scripts/sign_and_package.sh" notarize

DMG="$STAGE_DIST/MediaBrief-${VERSION}-macos-arm64.dmg"
MANIFEST="$STAGE_DIST/MediaBrief-${VERSION}-macos-arm64-manifest.json"
[ -f "$DMG" ] || { echo "❌ 发行命令结束但未找到 $DMG"; exit 1; }
[ -f "$MANIFEST" ] || { echo "❌ 发行命令结束但未找到 $MANIFEST"; exit 1; }

mkdir -p "$FINAL_DIST"
# 正式 dist 只留用户要下的 DMG 和核对用的清单。
rm -f "$FINAL_DIST"/MediaBrief-*-macos-arm64.zip \
    "$FINAL_DIST"/MediaBrief-*-notary.zip \
    "$FINAL_DIST"/mediabrief-macos-*.zip \
    "$FINAL_DIST"/notary-*.json \
    "$FINAL_DIST"/notarize-*.log \
    "$FINAL_DIST"/sign-*.log
ditto "$DMG" "$FINAL_DIST/$(basename "$DMG")"
ditto "$MANIFEST" "$FINAL_DIST/$(basename "$MANIFEST")"

echo "✅ 正式发行物: $FINAL_DIST/$(basename "$DMG")"
echo "✅ 发行清单:   $FINAL_DIST/$(basename "$MANIFEST")"
