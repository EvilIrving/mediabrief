#!/bin/bash

# MediaBrief 安装脚本

echo "🚀 MediaBrief 安装脚本"
echo "========================"

# 检查Python版本
echo "检查Python环境..."
python_version=$(python3 --version 2>&1 | cut -d' ' -f2)
if [[ -z "$python_version" ]]; then
    echo "❌ 未找到Python3，请先安装Python 3.8或更高版本"
    exit 1
fi
echo "✅ Python版本: $python_version"

# 检查pip
if ! command -v pip3 &> /dev/null; then
    echo "❌ 未找到pip3，请先安装pip"
    exit 1
fi
echo "✅ pip已安装"

# 安装Python依赖
echo ""
echo "安装Python依赖..."
pip3 install -r requirements.txt

if [ $? -eq 0 ]; then
    echo "✅ Python依赖安装完成"
else
    echo "❌ Python依赖安装失败"
    exit 1
fi

# 检查FFmpeg
echo ""
echo "检查FFmpeg..."
if command -v ffmpeg &> /dev/null; then
    echo "✅ FFmpeg已安装"
else
    echo "⚠️  FFmpeg未安装，正在尝试安装..."
    
    # 检测操作系统
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux
        if command -v apt-get &> /dev/null; then
            sudo apt-get update && sudo apt-get install -y ffmpeg
        elif command -v yum &> /dev/null; then
            sudo yum install -y ffmpeg
        else
            echo "❌ 无法自动安装FFmpeg，请手动安装"
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        if command -v brew &> /dev/null; then
            brew install ffmpeg
        else
            echo "❌ 请先安装Homebrew，然后运行: brew install ffmpeg"
        fi
    else
        echo "❌ 不支持的操作系统，请手动安装FFmpeg"
    fi
fi

# 创建必要的目录
echo ""
echo "创建必要的目录..."
mkdir -p temp static
echo "✅ 目录创建完成"

# 构建前端（React SPA）。仅当存在 frontend/ 且本地有 pnpm 时执行；
# 发行版已内置 static/dist 构建产物，普通用户无需 Node 环境。
if [ -d "frontend" ] && command -v pnpm &> /dev/null; then
    echo ""
    echo "构建前端 (React)..."
    (cd frontend && pnpm install && pnpm run build)
    if [ $? -eq 0 ]; then
        echo "✅ 前端构建完成 (static/dist)"
    else
        echo "⚠️  前端构建失败，将回退到已内置的 static/dist"
    fi
fi

# 设置权限
chmod +x start.py

echo ""
echo "🎉 安装完成!"
echo ""
echo "使用方法:"
echo "  1. 启动服务:"
echo "     python3 start.py"
echo ""
echo "  2. 打开浏览器访问: http://localhost:8000"
echo ""
echo "  3. 在页面 AI Settings 面板中配置 API Key、API Base URL 和模型"
echo ""
echo "支持的视频平台:"
echo "  - YouTube"
echo "  - Bilibili"
echo "  - 其他yt-dlp支持的平台"
