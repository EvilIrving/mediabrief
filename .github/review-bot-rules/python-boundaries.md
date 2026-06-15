# python-boundaries — 后端三层边界

## 规则

后端代码必须保持三层分离：**路由（routers/）→ 编排（pipeline.py）→ 服务（services/）**。不可反向依赖。

## 依赖方向

```
routers/        ← HTTP 请求/响应处理，参数提取
  ↓ 可导入
pipeline.py     ← 任务编排，阶段调度，后台任务执行
  ↓ 可导入
services/       ← 具体实现：transcriber, summarizer, translator, sanitizer
task_store.py   ← 任务状态、SSE 广播（共享状态）
cancellation.py ← 取消令牌（共享基础设施）
db.py           ← 数据库操作（共享基础设施）
```

## 禁止的反向依赖

```python
# ❌ services/ 下的文件导入 routers/
from routers.core import router         # ❌ 服务层不能导入路由层

# ❌ pipeline.py 导入 router 模块
from routers.transcribe import router   # ❌ 编排层不能导入路由

# ❌ 跨服务直接构造
import transcriber                      # ❌ 应该通过 services.py 单例获取
```

## 正确 ✓

```python
# routers/ 中使用服务（通过 services.py 单例）
from services import summarizer, transcriber

# pipeline.py 中使用服务和状态
from services import summarizer
from task_store import tasks, broadcast_update
from cancellation import cancelled

# 新的服务模块不需要导入路由
```


## 为什么

三层分离保证了：路由可以独立重构 HTTP 接口而不影响业务逻辑；pipeline 可以调整编排而不影响具体实现；服务可以被测试和替换而不依赖 HTTP 层。
