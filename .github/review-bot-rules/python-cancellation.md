# python-cancellation — 协作式取消

## 规则

所有长时间运行的操作（转写、摘要、翻译、LLM 调用、媒体处理）必须在合适的检查点调用 `cancellation.cancelled(task_id)` 或等效取消检查。

## 必须检查取消的场景

- LLM API 调用循环中
- Whisper 转写分段处理中
- yt-dlp 下载 / FFmpeg 处理中
- 任何超过 2 秒的同步或异步操作循环中

## 正确 ✓

```python
from cancellation import cancelled

async def long_running_task(task_id: str):
    for chunk in chunks:
        if cancelled(task_id):
            raise TaskCancelledException(task_id)
        await process(chunk)
```

## 错误 ✗

```python
# ❌ 长循环中没有任何取消检查
async def transcribe(task_id: str, audio_path: str):
    for segment in model.transcribe(audio_path):
        result.append(segment.text)
        # 用户点了取消，但这里无法响应
```

## 子进程安全

使用 `_run_media_proc` 或等效方式运行 ffmpeg/ffprobe 子进程时，必须：
1. 传入取消 token（`cancel_token`）
2. 设置超时（`timeout` 参数）
3. 不使用 `shell=True`
4. 设置进程组以便取消时回收整个进程树
