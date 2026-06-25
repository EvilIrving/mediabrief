#!/usr/bin/env bash
# 模型下载网络诊断脚本
# 用途：判断 HuggingFace 模型下不下来到底是「连不上」还是「太慢」，
#       并对比不同线路/镜像的真实持续下载速度。
# 用法：bash scripts/test_download_speed.sh
set -u

HF_FILE="https://huggingface.co/mlx-community/whisper-base-mlx/resolve/main/weights.npz"
HF_TURBO="https://huggingface.co/mlx-community/whisper-large-v3-turbo/resolve/main/weights.safetensors"
MIRROR_FILE="https://hf-mirror.com/mlx-community/whisper-base-mlx/resolve/main/weights.npz"
CF_SPEED="https://speed.cloudflare.com/__down?bytes=20000000"

line() { printf '%.0s─' {1..60}; echo; }
test_url() {
  local label="$1" url="$2"; shift 2
  printf "%-28s " "$label"
  curl -sL --max-time 12 -o /dev/null \
    -w "HTTP %{http_code} | 速度 %{speed_download} B/s | 连接 %{time_connect}s\n" \
    "$@" "$url" 2>&1 | tail -1
}

line
echo "1) 网络环境"
line
echo "代理环境变量:"; env | grep -iE "proxy" || echo "  (无)"
echo "Clash/代理监听端口:";
lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | grep -iE "clash|mihomo|verge" || echo "  (未检测到 Clash 进程)"
echo "huggingface.co DNS 解析:"; nslookup huggingface.co 2>&1 | tail -3

line
echo "2) 持续下载测速（看吞吐，不是延迟）"
line
test_url "Cloudflare 测速(20MB)"   "$CF_SPEED"
test_url "HuggingFace base 权重"    "$HF_FILE"
test_url "HuggingFace turbo 权重"   "$HF_TURBO"
test_url "hf-mirror 直连"           "$MIRROR_FILE" --noproxy '*'

line
echo "判读："
echo "  • HF 速度 ≈ Cloudflare 速度  → 线路整体吞吐就这样，不是 HF 的问题"
echo "  • HF 明显慢于 Cloudflare      → HF 被限速/路由差，换镜像或挂代理"
echo "  • HF 是 0 / HTTP 000          → 连不上（DNS 被解析到墙内或节点断流）"
echo "  • 任意 >1 MB/s                → 正常，直接在前端点下载即可"
line
