# frontend-i18n — 前端国际化

## 规则

所有用户可见的 UI 文本必须来自 `frontend/src/i18n/dictionaries.ts`，组件中禁止硬编码字符串。四种语言 (en, zh, ja, ko) 必须同步更新。

## 正确 ✓

```tsx
// 从 context 获取 i18n
const { t } = useI18n()

// 组件中使用
<button>{t('start_transcription')}</button>
<p>{t('empty_hint')}</p>
<ErrorBanner message={t('error_processing_failed') + reason} />
```

```ts
// dictionaries.ts —— 添加新 key 时必须覆盖四种语言
const en: Dict = {
  ...existing,
  new_feature_label: 'My Feature',
}
const zh: Dict = {
  ...existing,
  new_feature_label: '我的功能',
}
const ja: Dict = {
  ...existing,
  new_feature_label: 'マイ機能',
}
const ko: Dict = {
  ...existing,
  new_feature_label: '내 기능',
}
```

## 错误 ✗

```tsx
// ❌ 组件中硬编码字符串
<h2>Download History</h2>
<button>Start Transcription</button>
<p>No results found.</p>

// ❌ 只更新了一种语言
const en: Dict = { new_key: 'Hello' }
// zh, ja, ko 缺失 new_key
```

## 例外

- 技术性标识符（CSS class、data-attribute、key prop）
- 开发工具专用组件（只在调试模式出现）
- 来自后端的动态数据（视频标题、转录文本等技术内容）
- 已标注 `// TODO: i18n` 且有对应 issue 的临时硬编码
