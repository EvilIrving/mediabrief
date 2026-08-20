#!/usr/bin/env bash
#
# MediaBrief macOS Developer ID 签名、公证与 DMG 打包。
#
# 一次性配置公证凭据（密码只写入 macOS Keychain）：
#   bash scripts/sign_and_package.sh setup-notary
#
# 常用操作：
#   bash scripts/sign_and_package.sh sign       # 签名并验证 .app
#   bash scripts/sign_and_package.sh dmg        # 签名 .app，创建并签名 DMG（不公证）
#   bash scripts/sign_and_package.sh notarize   # 完整发行：签名、公证、staple、验证
#
# 可选环境变量：
#   APPLE_DEVELOPER_ID  Developer ID Application 身份名称或 SHA-1；未设置时仅允许本机恰好有一个
#   NOTARY_PROFILE      notarytool Keychain profile；默认 mediabrief-notary
#   SIGNING_KEYCHAIN    可选的签名钥匙串路径；公证 profile 仍从默认钥匙串搜索范围读取
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
DIST_DIR="${DIST_DIR:-$ROOT/dist}"
APP_NAME="MediaBrief"
APP_PATH="${APP_PATH:-$DIST_DIR/$APP_NAME.app}"
MAIN_ENTITLEMENTS="$ROOT/pyinstaller/entitlements.plist"
DENO_ENTITLEMENTS="$ROOT/pyinstaller/deno-entitlements.plist"
NOTARY_PROFILE="${NOTARY_PROFILE:-mediabrief-notary}"
SIGNING_KEYCHAIN="${SIGNING_KEYCHAIN:-}"
ACTION="${1:-sign}"

SIGNING_ID=""
APP_VERSION=""
BUILD_VERSION=""
DMG_PATH=""
APP_SUBMISSION_ID=""
DMG_SUBMISSION_ID=""
ACTIVE_MOUNT=""

cd "$ROOT"

fail() {
    echo "❌ $*" >&2
    exit 1
}

cleanup_mount() {
    if [ -n "$ACTIVE_MOUNT" ] && mount | grep -Fq " on $ACTIVE_MOUNT "; then
        hdiutil detach "$ACTIVE_MOUNT" >/dev/null 2>&1 || true
    fi
    if [ -n "$ACTIVE_MOUNT" ] && [ -d "$ACTIVE_MOUNT" ]; then
        rmdir "$ACTIVE_MOUNT" >/dev/null 2>&1 || true
    fi
}
trap cleanup_mount EXIT

require_tool() {
    command -v "$1" >/dev/null 2>&1 || fail "缺少必需工具: $1"
}

require_app() {
    [ -d "$APP_PATH" ] || fail "未找到 $APP_PATH；请先运行 bash scripts/build_macos.sh"
    [ -f "$APP_PATH/Contents/Info.plist" ] || fail "应用缺少 Contents/Info.plist"
    [ -f "$MAIN_ENTITLEMENTS" ] || fail "缺少主进程权限文件: $MAIN_ENTITLEMENTS"
    [ -f "$DENO_ENTITLEMENTS" ] || fail "缺少 Deno 权限文件: $DENO_ENTITLEMENTS"

    APP_VERSION=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP_PATH/Contents/Info.plist")
    BUILD_VERSION=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$APP_PATH/Contents/Info.plist")
    [ -n "$APP_VERSION" ] || fail "CFBundleShortVersionString 为空"
    [ -n "$BUILD_VERSION" ] || fail "CFBundleVersion 为空"
    local expected_version
    [ -f "$ROOT/VERSION" ] || fail "缺少单一版本来源: $ROOT/VERSION"
    expected_version=$(tr -d '[:space:]' < "$ROOT/VERSION")
    [ "$APP_VERSION" = "$expected_version" ] || fail "应用版本 $APP_VERSION 与 VERSION $expected_version 不一致，请重新构建"
    [ "$BUILD_VERSION" = "$expected_version" ] || fail "构建版本 $BUILD_VERSION 与 VERSION $expected_version 不一致，请重新构建"
    DMG_PATH="$DIST_DIR/MediaBrief-${APP_VERSION}-macos-arm64.dmg"
}

resolve_signing_identity() {
    local requested="${APPLE_DEVELOPER_ID:-}"
    local identities matches count

    if [ -n "$SIGNING_KEYCHAIN" ]; then
        identities=$(security find-identity -v -p codesigning "$SIGNING_KEYCHAIN" 2>/dev/null | grep '"Developer ID Application:' || true)
    else
        identities=$(security find-identity -v -p codesigning 2>/dev/null | grep '"Developer ID Application:' || true)
    fi
    [ -n "$identities" ] || fail "Keychain 中没有有效的 Developer ID Application 证书"

    if [ -n "$requested" ]; then
        matches=$(printf '%s\n' "$identities" | grep -F -- "$requested" || true)
        count=$(printf '%s\n' "$matches" | awk 'NF { count++ } END { print count + 0 }')
        [ "$count" -eq 1 ] || fail "APPLE_DEVELOPER_ID 未唯一匹配有效的 Developer ID Application 身份"
        SIGNING_ID=$(printf '%s\n' "$matches" | awk 'NR == 1 { print $2 }')
    else
        count=$(printf '%s\n' "$identities" | awk 'NF { count++ } END { print count + 0 }')
        [ "$count" -eq 1 ] || fail "发现 $count 个 Developer ID Application 身份；请设置 APPLE_DEVELOPER_ID 明确选择"
        SIGNING_ID=$(printf '%s\n' "$identities" | awk 'NR == 1 { print $2 }')
    fi

    [ -n "$SIGNING_ID" ] || fail "无法解析 Developer ID Application 身份"
    echo "🔐 Developer ID Application: ${SIGNING_ID:0:12}…"
}

# Apple 时间戳偶发不可用；短重试避免整包重做。
codesign_with_retry() {
    local attempt=1
    local max_attempts=5
    local delay=3
    local err
    local -a codesign_args=("$@")
    if [ -n "$SIGNING_KEYCHAIN" ]; then
        codesign_args=(--keychain "$SIGNING_KEYCHAIN" "${codesign_args[@]}")
    fi
    while [ "$attempt" -le "$max_attempts" ]; do
        if err=$(codesign "${codesign_args[@]}" 2>&1); then
            return 0
        fi
        if printf '%s\n' "$err" | grep -Eqi 'timestamp service is not available|A timestamp was expected|internal error in Code Signing subsystem'; then
            echo "   ⚠️  codesign 时间戳失败 (attempt $attempt/$max_attempts)，${delay}s 后重试…" >&2
            sleep "$delay"
            delay=$((delay * 2))
            attempt=$((attempt + 1))
            continue
        fi
        printf '%s\n' "$err" >&2
        return 1
    done
    printf '%s\n' "$err" >&2
    return 1
}

sign_macho_file() {
    local binary="$1"
    local name
    name=$(basename "$binary")

    if [ "$name" = "deno" ]; then
        codesign_with_retry --force --options runtime --timestamp \
            --entitlements "$DENO_ENTITLEMENTS" \
            --sign "$SIGNING_ID" "$binary"
    else
        codesign_with_retry --force --options runtime --timestamp \
            --sign "$SIGNING_ID" "$binary"
    fi
}

sign_nested_code() {
    local binary bundle macho_list

    echo "   签名嵌套 Mach-O…"
    macho_list=$(mktemp "/tmp/mediabrief-machos.XXXXXX")
    find "$APP_PATH/Contents" -type f -print0 >"$macho_list"
    while IFS= read -r -d '' binary; do
        if [ -f "$binary" ] && file -b "$binary" | grep -q 'Mach-O'; then
            sign_macho_file "$binary"
        fi
    done <"$macho_list"
    rm -f "$macho_list"

    # framework / helper bundle 必须在其内部 Mach-O 之后、主 .app 之前签名。
    while IFS= read -r bundle; do
        [ -n "$bundle" ] || continue
        codesign_with_retry --force --options runtime --timestamp --sign "$SIGNING_ID" "$bundle"
    done < <(find "$APP_PATH/Contents" -type d \( -name '*.framework' -o -name '*.xpc' -o -name '*.app' \) -print | awk '{ print length, $0 }' | sort -rn | cut -d' ' -f2-)
}

verify_app_signature() {
    echo "   验证 .app 签名…"
    codesign --verify --deep --strict --verbose=2 "$APP_PATH"

    local deno="$APP_PATH/Contents/MacOS/deno"
    if [ -x "$deno" ]; then
        "$deno" eval 'if (1 + 1 !== 2) Deno.exit(1)'
    fi
}

sign_app() {
    resolve_signing_identity
    echo "🔏 签名 $APP_NAME.app"
    sign_nested_code
    codesign_with_retry --force --options runtime --timestamp \
        --entitlements "$MAIN_ENTITLEMENTS" \
        --sign "$SIGNING_ID" "$APP_PATH"
    verify_app_signature
    echo "   ✅ .app 已完成 Developer ID 签名"
}

require_notary_profile() {
    xcrun --find notarytool >/dev/null 2>&1 || fail "当前 Xcode 不包含 notarytool"
    if ! xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" --output-format json >/dev/null 2>&1; then
        fail "公证 Keychain profile '$NOTARY_PROFILE' 不存在或无效；先运行 bash scripts/sign_and_package.sh setup-notary"
    fi
}

notarize_file() {
    local input="$1"
    local label="$2"
    local submit_json
    local log_json
    # macOS mktemp 要求 XXXXXX 在模板末尾，不能再跟 .json
    submit_json=$(mktemp "${TMPDIR:-/tmp}/mediabrief-notary-${label}-submit.XXXXXX")
    log_json=$(mktemp "${TMPDIR:-/tmp}/mediabrief-notary-${label}-log.XXXXXX")
    local status submission_id

    echo "📤 提交 ${label} 公证…"
    if ! xcrun notarytool submit "$input" \
        --keychain-profile "$NOTARY_PROFILE" \
        --wait \
        --output-format json >"$submit_json"; then
        fail "${label} 公证提交失败；响应已保存到 $submit_json"
    fi

    status=$(plutil -extract status raw -o - "$submit_json" 2>/dev/null || true)
    submission_id=$(plutil -extract id raw -o - "$submit_json" 2>/dev/null || true)
    [ -n "$submission_id" ] || fail "${label} 公证响应缺少 submission ID: $submit_json"

    xcrun notarytool log "$submission_id" \
        --keychain-profile "$NOTARY_PROFILE" \
        "$log_json" >/dev/null

    [ "$status" = "Accepted" ] || fail "${label} 公证状态为 '$status'；检查 $log_json"

    if [ "$label" = "app" ]; then
        APP_SUBMISSION_ID="$submission_id"
    else
        DMG_SUBMISSION_ID="$submission_id"
    fi
    echo "   ✅ ${label} 公证已接受: $submission_id"
}

notarize_and_staple_app() {
    local zip_path
    # macOS mktemp 要求 XXXXXX 在模板末尾，不能再跟 .zip
    zip_path=$(mktemp "${TMPDIR:-/tmp}/mediabrief-notary.XXXXXX")
    mv "$zip_path" "${zip_path}.zip"
    zip_path="${zip_path}.zip"

    ditto -c -k --keepParent "$APP_PATH" "$zip_path"
    notarize_file "$zip_path" app
    rm -f "$zip_path"

    echo "📎 Staple .app…"
    xcrun stapler staple "$APP_PATH"
    xcrun stapler validate "$APP_PATH"
    spctl --assess --type execute --verbose=2 "$APP_PATH"
}

create_signed_dmg() {
    local stage
    stage=$(mktemp -d "$DIST_DIR/.dmg-staging.XXXXXX")

    echo "💿 创建并签名 DMG…"
    ditto "$APP_PATH" "$stage/$APP_NAME.app"
    ln -s /Applications "$stage/Applications"

    if [ -e "$DMG_PATH" ]; then
        rm -f "$DMG_PATH"
    fi
    hdiutil create -volname "$APP_NAME" \
        -srcfolder "$stage" \
        -format UDZO \
        "$DMG_PATH"
    rm -rf "$stage"

    codesign_with_retry --force --timestamp --sign "$SIGNING_ID" "$DMG_PATH"
    codesign --verify --strict --verbose=2 "$DMG_PATH"
    hdiutil verify "$DMG_PATH" >/dev/null
    echo "   ✅ DMG 已签名: $DMG_PATH"
}

verify_distribution() {
    local mounted_app
    ACTIVE_MOUNT=$(mktemp -d "/tmp/mediabrief-mount.XXXXXX")
    hdiutil attach -readonly -nobrowse -mountpoint "$ACTIVE_MOUNT" "$DMG_PATH" >/dev/null
    mounted_app="$ACTIVE_MOUNT/$APP_NAME.app"

    [ -d "$mounted_app" ] || fail "DMG 中缺少 $APP_NAME.app"
    [ -L "$ACTIVE_MOUNT/Applications" ] || fail "DMG 中缺少 Applications 快捷方式"
    codesign --verify --deep --strict --verbose=2 "$mounted_app"
    xcrun stapler validate "$mounted_app"
    spctl --assess --type execute --verbose=2 "$mounted_app"

    hdiutil detach "$ACTIVE_MOUNT" >/dev/null
    rmdir "$ACTIVE_MOUNT"
    ACTIVE_MOUNT=""

    codesign --verify --strict --verbose=2 "$DMG_PATH"
    xcrun stapler validate "$DMG_PATH"
    spctl --assess --type open --context context:primary-signature --verbose=2 "$DMG_PATH"
    echo "   ✅ DMG 与内含 .app 已通过签名、staple 和 Gatekeeper 检查"
}

write_release_manifest() {
    local manifest="$DIST_DIR/MediaBrief-${APP_VERSION}-macos-arm64-manifest.json"
    local dmg_size dmg_sha created_at
    dmg_size=$(stat -f '%z' "$DMG_PATH")
    dmg_sha=$(shasum -a 256 "$DMG_PATH" | awk '{ print $1 }')
    created_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

    printf '%s\n' \
        '{' \
        "  \"product\": \"$APP_NAME\"," \
        "  \"version\": \"$APP_VERSION\"," \
        "  \"buildVersion\": \"$BUILD_VERSION\"," \
        '  "architecture": "arm64",' \
        "  \"artifact\": \"$(basename "$DMG_PATH")\"," \
        "  \"sizeBytes\": $dmg_size," \
        "  \"sha256\": \"$dmg_sha\"," \
        "  \"signingIdentitySha1\": \"$SIGNING_ID\"," \
        "  \"appNotarySubmissionId\": \"$APP_SUBMISSION_ID\"," \
        "  \"dmgNotarySubmissionId\": \"$DMG_SUBMISSION_ID\"," \
        '  "codesign": "valid",' \
        '  "staple": "valid",' \
        '  "gatekeeper": "accepted",' \
        "  \"createdAt\": \"$created_at\"" \
        '}' >"$manifest"
    # plutil -lint 在部分 macOS 版本只按 plist 语法检查；extract 会实际解析 JSON。
    plutil -extract product raw -o - "$manifest" >/dev/null
    echo "🧾 发行清单: $manifest"
}

setup_notary_profile() {
    xcrun --find notarytool >/dev/null 2>&1 || fail "当前 Xcode 不包含 notarytool"
    echo "将把 Apple ID、Team ID 与 app-specific password 安全保存到 macOS Keychain。"
    echo "profile: $NOTARY_PROFILE"
    xcrun notarytool store-credentials "$NOTARY_PROFILE"
    require_notary_profile
    echo "✅ 公证凭据已保存并通过验证"
}

echo "MediaBrief macOS release — $ACTION"

case "$ACTION" in
    setup-notary)
        setup_notary_profile
        ;;
    sign)
        require_app
        sign_app
        ;;
    dmg)
        require_app
        sign_app
        create_signed_dmg
        ;;
    notarize)
        require_app
        require_notary_profile
        sign_app
        notarize_and_staple_app
        create_signed_dmg
        notarize_file "$DMG_PATH" dmg
        echo "📎 Staple DMG…"
        xcrun stapler staple "$DMG_PATH"
        xcrun stapler validate "$DMG_PATH"
        verify_distribution
        write_release_manifest
        echo "🎉 正式发行物已完成: $DMG_PATH"
        ;;
    *)
        fail "未知操作 '$ACTION'；可用: setup-notary | sign | dmg | notarize"
        ;;
esac
