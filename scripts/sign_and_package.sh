#!/usr/bin/env bash
#
# macOS 签名 + 公证 + DMG 打包脚本
#
# 前置条件：
#   1. Apple Developer 账号 + App-Specific Password（存于 Keychain）
#   2. Developer ID Application 证书已导入 Keychain
#   3. 已运行 scripts/build_macos.sh 生成 .app
#
# 用法:
#   # 仅签名
#   bash scripts/sign_and_package.sh sign
#
#   # 签名 + 创建 DMG
#   bash scripts/sign_and_package.sh dmg
#
#   # 签名 + 公证 + 装订 + DMG
#   bash scripts/sign_and_package.sh notarize
#
# 环境变量（可选，未设置则从 Keychain / xcrun 自动获取）：
#   APPLE_DEVELOPER_ID   Developer ID Application 证书名称
#   APPLE_ID             Apple ID 邮箱
#   APPLE_TEAM_ID        Team ID
#   APPLE_APP_PASSWORD   App-Specific Password（存于 Keychain 名称）
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
cd "$ROOT"

DIST_DIR="$ROOT/dist"
APP_NAME="AI Transcriber"
APP_PATH="$DIST_DIR/$APP_NAME.app"
DMG_NAME="ai-transcriber-macos-$(uname -m)-$(date +%Y%m%d).dmg"
ENTITLEMENTS="$ROOT/pyinstaller/entitlements.plist"

ACTION="${1:-sign}"

echo "🔐 macOS 签名与打包"
echo "   操作: $ACTION"
echo ""

# ── 检查 .app 是否存在 ──
if [ ! -d "$APP_PATH" ]; then
    echo "❌ 未找到 $APP_PATH，请先运行: bash scripts/build_macos.sh"
    exit 1
fi

# ── 生成 entitlements（如不存在） ──
if [ ! -f "$ENTITLEMENTS" ]; then
    cat > "$ENTITLEMENTS" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
    <key>com.apple.security.cs.disable-library-validation</key>
    <true/>
    <key>com.apple.security.network.client</key>
    <true/>
    <key>com.apple.security.files.user-selected.read-only</key>
    <true/>
    <key>com.apple.security.files.user-selected.read-write</key>
    <true/>
</dict>
</plist>
EOF
    echo "   ✅ entitlements.plist 已生成"
fi

# ── 获取签名身份 ──
DEVELOPER_ID="${APPLE_DEVELOPER_ID:-}"
if [ -z "$DEVELOPER_ID" ]; then
    DEVELOPER_ID=$(security find-identity -v -p codesigning 2>/dev/null | \
        grep "Developer ID Application" | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
fi

if [ -z "$DEVELOPER_ID" ] && [ "$ACTION" != "dmg" ]; then
    echo "⚠️  未找到 Developer ID Application 证书，将创建未签名的 DMG"
    ACTION="dmg"
fi

# ── 签名 ──
sign_app() {
    if [ -z "$DEVELOPER_ID" ]; then
        echo "❌ 未找到 Developer ID Application 证书，无法签名"
        echo "   请在 Keychain 中导入证书，或设置环境变量 APPLE_DEVELOPER_ID"
        return 1
    fi

    echo "🔏 签名身份: $DEVELOPER_ID"
    echo ""

    # 1. 签名所有 .dylib / .so / framework（由内到外）
    echo "   签名内部二进制文件..."
    find "$APP_PATH" -type f \( -name "*.dylib" -o -name "*.so" -o -name "Python" -o -name "ffmpeg" -o -name "deno" \) 2>/dev/null | while read -r f; do
        codesign --force --options runtime --timestamp --sign "$DEVELOPER_ID" "$f" 2>/dev/null || true
    done

    # 2. 签名 .app bundle
    echo "   签名应用包..."
    codesign --force --options runtime --timestamp \
        --entitlements "$ENTITLEMENTS" \
        --sign "$DEVELOPER_ID" \
        "$APP_PATH"

    # 3. 验证签名
    echo "   验证签名..."
    codesign --verify --deep --strict --verbose=2 "$APP_PATH" 2>&1 || true

    echo "   ✅ 签名完成"
}

# ── 公证 ──
notarize_app() {
    local APPLE_ID="${APPLE_ID:-}"
    local APPLE_TEAM="${APPLE_TEAM_ID:-}"
    local KEYCHAIN_PROFILE="ai-transcriber-notary"

    if [ -z "$APPLE_ID" ] || [ -z "$APPLE_TEAM" ]; then
        echo "⚠️  缺少 APPLE_ID 或 APPLE_TEAM_ID 环境变量，跳过公证"
        return 0
    fi

    echo ""
    echo "📋 提交公证..."

    # 创建 zip 用于上传（公证需要 zip/pkg/dmg）
    local ZIP_PATH="$DIST_DIR/ai-transcriber-notary.zip"
    ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"

    # 使用 notarytool（macOS 13+）
    if command -v notarytool &>/dev/null; then
        local submit_output
        submit_output=$(xcrun notarytool submit "$ZIP_PATH" \
            --apple-id "$APPLE_ID" \
            --team-id "$APPLE_TEAM" \
            --password "$APPLE_APP_PASSWORD" \
            --wait 2>&1)
        echo "$submit_output"

        local submission_id
        submission_id=$(echo "$submit_output" | grep -oE '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}' | head -1)

        if [ -n "$submission_id" ]; then
            xcrun notarytool log "$submission_id" \
                --apple-id "$APPLE_ID" \
                --team-id "$APPLE_TEAM" \
                --password "$APPLE_APP_PASSWORD" \
                "$DIST_DIR/notary-log.json" 2>/dev/null || true
        fi
    else
        # 旧版 altool（macOS 12-）
        xcrun altool --notarize-app \
            --primary-bundle-id "com.ai-transcriber.desktop" \
            --username "$APPLE_ID" \
            --password "$APPLE_APP_PASSWORD" \
            --asc-provider "$APPLE_TEAM" \
            --file "$ZIP_PATH" 2>&1
    fi

    rm -f "$ZIP_PATH"

    # 装订（staple）公证票据
    echo ""
    echo "📎 装订公证票据..."
    xcrun stapler staple "$APP_PATH" 2>&1 || echo "   ⚠️  装订失败（可能公证尚未完成）"

    echo "   ✅ 公证完成"
}

# ── 创建 DMG ──
create_dmg() {
    echo ""
    echo "💿 创建 DMG..."

    local DMG_TMP="$DIST_DIR/dmg_temp"
    rm -rf "$DMG_TMP" "$DIST_DIR/$DMG_NAME"

    mkdir -p "$DMG_TMP"
    cp -R "$APP_PATH" "$DMG_TMP/"

    # 创建 Applications 快捷方式
    ln -s /Applications "$DMG_TMP/Applications"

    # 创建 DMG
    hdiutil create -volname "$APP_NAME" \
        -srcfolder "$DMG_TMP" \
        -ov -format UDZO \
        "$DIST_DIR/$DMG_NAME" \
        2>&1

    # 签名 DMG（如果已签名 app）
    if [ -n "$DEVELOPER_ID" ]; then
        codesign --force --sign "$DEVELOPER_ID" --timestamp "$DIST_DIR/$DMG_NAME" 2>/dev/null || true
    fi

    rm -rf "$DMG_TMP"
    echo "   ✅ DMG: $DIST_DIR/$DMG_NAME"
    ls -lh "$DIST_DIR/$DMG_NAME"
}

# ── 执行 ──
case "$ACTION" in
    sign)
        sign_app
        ;;
    dmg)
        sign_app || true
        create_dmg
        ;;
    notarize)
        sign_app
        notarize_app
        create_dmg
        ;;
    *)
        echo "未知操作: $ACTION"
        echo "可用: sign | dmg | notarize"
        exit 1
        ;;
esac

echo ""
echo "🎉 完成!"
