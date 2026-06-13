# Windows 打包脚本 — 构建 AI Transcriber 可执行目录
#
# 用法 (PowerShell):  powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
# 输出:  dist/AI Transcriber/
#
param(
    [switch]$SkipFFmpeg = $false
)

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ROOT

$DIST_DIR = Join-Path $ROOT "dist"
$BUILD_DIR = Join-Path $ROOT "build"
$APP_NAME = "AI Transcriber"
$DATE = Get-Date -Format "yyyyMMdd"
$ZIP_NAME = "ai-transcriber-windows-$DATE.zip"

Write-Host "🔨 开始构建 Windows 桌面应用..."
Write-Host "   项目根目录: $ROOT"

# ── 1. 检查虚拟环境 ──
$VENV_PYTHON = Join-Path $ROOT "venv\Scripts\python.exe"
if (-not (Test-Path $VENV_PYTHON)) {
    Write-Host "❌ 未找到虚拟环境，请先运行: python -m venv venv && venv\Scripts\activate && pip install -r requirements.txt"
    exit 1
}

Write-Host ""
Write-Host "📦 步骤 1/4: 安装打包依赖..."
& $VENV_PYTHON -m pip install -q pyinstaller pywebview

# ── 2. 下载 FFmpeg ──
$FFMPEG_DIR = Join-Path $ROOT "ffmpeg_bin"
New-Item -ItemType Directory -Force -Path $FFMPEG_DIR | Out-Null

if (-not $SkipFFmpeg) {
    Write-Host ""
    Write-Host "📦 步骤 2/4: 准备 FFmpeg..."

    $FFMPEG_EXE = Join-Path $FFMPEG_DIR "ffmpeg.exe"
    if (Test-Path $FFMPEG_EXE) {
        Write-Host "   FFmpeg 已存在，跳过下载"
    } else {
        Write-Host "   下载 FFmpeg (Windows)..."
        $FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        $TMP_ZIP = Join-Path $env:TEMP "ffmpeg_windows.zip"
        $TMP_DIR = Join-Path $env:TEMP "ffmpeg_windows_extract"

        try {
            Invoke-WebRequest -Uri $FFMPEG_URL -OutFile $TMP_ZIP -UseBasicParsing
            Expand-Archive -Path $TMP_ZIP -DestinationPath $TMP_DIR -Force
            # 从解压目录中复制 ffmpeg.exe
            $EXTRACTED = Get-ChildItem -Path $TMP_DIR -Filter "ffmpeg.exe" -Recurse | Select-Object -First 1
            if ($EXTRACTED) {
                Copy-Item $EXTRACTED.FullName $FFMPEG_EXE -Force
                Copy-Item (Join-Path $EXTRACTED.DirectoryName "ffprobe.exe") $FFMPEG_DIR -Force -ErrorAction SilentlyContinue
                Write-Host "   ✅ FFmpeg 就绪: $FFMPEG_EXE"
            }
        } catch {
            Write-Host "   ⚠️  下载失败: $_"
            Write-Host "   请手动下载 ffmpeg.exe 放到 $FFMPEG_DIR"
        } finally {
            Remove-Item $TMP_ZIP -Force -ErrorAction SilentlyContinue
            Remove-Item $TMP_DIR -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
} else {
    Write-Host ""
    Write-Host "📦 步骤 2/4: 跳过 FFmpeg (--SkipFFmpeg)"
}

# ── 3. PyInstaller 打包 ──
Write-Host ""
Write-Host "📦 步骤 3/4: PyInstaller 打包..."

if (Test-Path (Join-Path $DIST_DIR $APP_NAME)) {
    Remove-Item (Join-Path $DIST_DIR $APP_NAME) -Recurse -Force -ErrorAction SilentlyContinue
}
if (Test-Path (Join-Path $BUILD_DIR $APP_NAME)) {
    Remove-Item (Join-Path $BUILD_DIR $APP_NAME) -Recurse -Force -ErrorAction SilentlyContinue
}

$SPEC_FILE = Join-Path $ROOT "pyinstaller\ai_transcriber.spec"
& $VENV_PYTHON -m PyInstaller `
    --distpath $DIST_DIR `
    --workpath $BUILD_DIR `
    --noconfirm `
    --clean `
    $SPEC_FILE

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ PyInstaller 打包失败"
    exit $LASTEXITCODE
}

# ── 4. 复制 FFmpeg 到打包目录 ──
Write-Host ""
Write-Host "📦 步骤 4/4: 复制 FFmpeg..."

$APP_OUTPUT = Join-Path $DIST_DIR $APP_NAME
$FFMPEG_SRC = Join-Path $FFMPEG_DIR "ffmpeg.exe"

if (Test-Path $APP_OUTPUT) {
    if (Test-Path $FFMPEG_SRC) {
        Copy-Item $FFMPEG_SRC $APP_OUTPUT -Force
        $FFPROBE_SRC = Join-Path $FFMPEG_DIR "ffprobe.exe"
        if (Test-Path $FFPROBE_SRC) {
            Copy-Item $FFPROBE_SRC $APP_OUTPUT -Force
        }
        Write-Host "   ✅ FFmpeg 已复制到 $APP_OUTPUT"
    }

    # ── 复制 Deno（YouTube nsig 签名解算所需的 JS 运行时） ──
    # 缺失时 YouTube 下载/转录会报 "Requested format is not available"。
    # start.py 会在 exe 同级目录查找 deno.exe 并注入 PATH。
    $DENO_DIR = Join-Path $ROOT "deno_bin"
    $DENO_SRC = Join-Path $DENO_DIR "deno.exe"
    if (-not (Test-Path $DENO_SRC)) {
        Write-Host "   ⬇️  下载 Deno (Windows)..."
        New-Item -ItemType Directory -Force -Path $DENO_DIR | Out-Null
        $DENO_URL = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
        $DENO_ZIP = Join-Path $env:TEMP "deno_windows.zip"
        $DENO_TMP = Join-Path $env:TEMP "deno_windows_extract"
        try {
            Invoke-WebRequest -Uri $DENO_URL -OutFile $DENO_ZIP -UseBasicParsing
            Expand-Archive -Path $DENO_ZIP -DestinationPath $DENO_TMP -Force
            $DENO_FOUND = Get-ChildItem -Path $DENO_TMP -Filter "deno.exe" -Recurse | Select-Object -First 1
            if ($DENO_FOUND) { Copy-Item $DENO_FOUND.FullName $DENO_SRC -Force }
        } catch {
            Write-Host "   ⚠️  Deno 下载失败，YouTube 签名解算可能不可用"
        }
    }
    if (Test-Path $DENO_SRC) {
        Copy-Item $DENO_SRC $APP_OUTPUT -Force
        Write-Host "   ✅ Deno 已复制到 $APP_OUTPUT"
    }

    # 模型/API 配置由前端设置页持久化，不在安装包中注入环境变量模板。
    # 创建启动批处理（方便用户双击）
    $BAT_PATH = Join-Path $APP_OUTPUT "启动AI Transcriber.bat"
    @"
@echo off
cd /d "%~dp0"
start "" "ai-transcriber.exe"
"@ | Out-File -FilePath $BAT_PATH -Encoding Default
    Write-Host "   ✅ 启动批处理已创建"
}

# ── 5. 打包 ZIP ──
Write-Host ""
Write-Host "📦 创建发布包..."
if (Test-Path $APP_OUTPUT) {
    $ZIP_PATH = Join-Path $DIST_DIR $ZIP_NAME
    Compress-Archive -Path $APP_OUTPUT -DestinationPath $ZIP_PATH -Force
    Write-Host "   ✅ 发布包: $ZIP_PATH"
}

Write-Host ""
Write-Host "🎉 构建完成!"
Write-Host "   输出位置: $DIST_DIR"
Get-ChildItem $DIST_DIR\*.zip | Format-Table Name, Length
