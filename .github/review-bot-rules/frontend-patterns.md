# frontend-patterns — 前端模式约定

## 错误处理

所有 transient 错误提示必须通过 `useAutoDismissError` + `<Toast>` / `<ErrorBanner>`，不使用临时 state。

```tsx
// ✓ 正确
const { error, setError, dismissError } = useAutoDismissError()

return (
  <>
    {error && <ErrorBanner message={error} onDismiss={dismissError} />}
    {/* 组件内容 */}
  </>
)

// ❌ 禁止——临时 state 做错误提示
const [errorMsg, setErrorMsg] = useState('')
{errorMsg && <div className="error">{errorMsg}</div>}
```

## API 调用

API 调用使用原生 `fetch`，base URL 从 `import.meta.env.BASE_URL` 获取。

```tsx
// ✓ 正确
const baseUrl = import.meta.env.BASE_URL
const res = await fetch(`${baseUrl}api/tasks/active`)
if (!res.ok) {
  const { detail } = await res.json()
  setError(detail)
  return
}
```

错误响应遵循 FastAPI schema: `{ detail: string }`。

## 组件约定

- 页面组件放在 `frontend/src/components/` 下，文件名用 PascalCase
- 共享工具函数放在 `frontend/src/lib/` 下
- 钩子放在 `frontend/src/hooks/` 下，以 `use` 开头
- 所有 UI 字符串来自 i18n dictionaries（见 `frontend-i18n.md`）
- 使用 Tailwind CSS utility class，不写自定义 CSS（除非是设计 token 变量）

## Design Tokens

在 `index.css` 中定义，使用 oklch 色彩空间：
- 深色优先，浅色适配
- 强调色：amber-copper (`oklch(58% 0.13 60)`)
- 最大宽度 720px（内容区），单列居中布局
- 工具式 UI——无渐变、无装饰性动画、无 hero 区域
