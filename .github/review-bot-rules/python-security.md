# python-security — 安全与密钥

## 规则

### 禁止硬编码密钥和凭据

```python
# ❌ 禁止
OPENAI_API_KEY = "sk-abc123..."
GITHUB_TOKEN = "ghp_..."
DATABASE_URL = "postgresql://user:pass@host/db"

# ✓ 正确——从前端请求体获取
@router.post("/api/transcribe")
async def transcribe(api_key: str = Form(""), base_url: str = Form("")):
    effective_key = (api_key or "").strip()
    client = openai.AsyncOpenAI(api_key=effective_key, base_url=base_url)
```

```python
# ✓ 正确——从环境变量获取（仅限启动脚本 start.py 需要的路径变量）
import os
ffmpeg_path = os.environ.get("AIT_FFMPEG")
```

### FFmpeg / FFprobe 必须使用绝对路径

禁止通过裸名称调用 ffmpeg/ffprobe 依赖 PATH：

```python
# ❌ 禁止
subprocess.run(["ffmpeg", "-i", input_path, output_path])

# ✓ 正确
import os
ffmpeg = os.environ.get("AIT_FFMPEG", "ffmpeg")
subprocess.run([ffmpeg, "-i", input_path, output_path])
```

### 禁止 shell=True

```python
# ❌ 禁止
subprocess.run(f"ffmpeg -i {input_path} {output_path}", shell=True)

# ✓ 正确
subprocess.run([ffmpeg, "-i", input_path, output_path])
```

`shell=True` 带来命令注入风险和跨平台引号问题，且子进程无法被取消令牌正确回收。

### 不要打印敏感信息

```python
# ❌ 禁止
logger.info(f"Using API key: {api_key}")
print(f"Token: {token}")

# ✓ 正确
logger.info("Using provided API key")
logger.info("API key present: %s", bool(api_key.strip()))
```

### 用户面错误不得泄漏实现细节

前端返回的错误信息不能包含：
- API 提供商名称（如 "OpenAI Error:"）
- 内部模块名或文件路径
- 数据库细节（如表名、SQL）
- 原始上游错误消息

应使用 `error_messages.humanize_error()` 转换后再返回前端。
