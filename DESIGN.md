# Design

## Visual Theme

**Scene:** A researcher at their desk, pasting links rapid-fire, scanning AI summaries between other tasks. The screen is a tool — glanced at, not admired. Ambient light varies from bright daylight to single-monitor midnight. The tool must feel fast and unobtrusive in both.

**Color strategy:** Restrained. Tinted warm neutrals with a single amber-copper accent (≈10% of surface). The warmth softens what would otherwise feel like a cold terminal tool. Dark by default because transcripts are long-form reading and dark reduces eye strain over 15-minute sessions; light mode for daytime desk workers who prefer it.

**Theme:** Dark-first, light-supported. System preference honored (`prefers-color-scheme`), explicit toggle respected.

## Color Palette

### Dark Theme (default)

| Token | Value | Usage |
|-------|-------|-------|
| `--bg` | `oklch(17% 0.004 75)` ≈ #0d0b09 | Page background |
| `--surface` | `oklch(22% 0.005 75)` ≈ #171310 | Cards, inputs, result panels |
| `--surface-2` | `oklch(27% 0.006 75)` ≈ #1f1b17 | Secondary surfaces, button backgrounds |
| `--surface-3` | `oklch(32% 0.007 75)` ≈ #27221d | Hover states, tertiary layers |
| `--border` | `oklch(38% 0.008 75)` ≈ #2e271f | Separators, input borders |
| `--border-light` | `oklch(44% 0.009 75)` ≈ #3a3028 | Dashed borders, drag zones |
| `--accent` | `oklch(58% 0.13 60)` ≈ #c07830 | Primary buttons, active states, progress bar |
| `--accent-h` | `oklch(63% 0.13 60)` ≈ #d08840 | Button hover, link hover |
| `--accent-dim` | `oklch(42% 0.10 60)` ≈ #7a4c1e | Muted accent, badges, focus rings |
| `--accent-text` | `oklch(68% 0.13 60)` ≈ #e0a060 | Active tab text, emphasis |
| `--text` | `oklch(88% 0.004 75)` ≈ #ddd5cb | Body text |
| `--text-muted` | `oklch(60% 0.006 75)` ≈ #7d6e62 | Secondary text, icons |
| `--text-dim` | `oklch(42% 0.006 75)` ≈ #4a3f38 | Placeholders, disabled text |
| `--success` | `oklch(65% 0.12 145)` ≈ #6ab87a | Success states, done indicators |
| `--error` | `oklch(58% 0.15 25)` ≈ #e07878 | Error text, destructive hints |

### Light Theme

| Token | Value | Usage |
|-------|-------|-------|
| `--bg` | `oklch(97% 0.004 85)` ≈ #faf8f5 | Page background |
| `--surface` | `oklch(100% 0 0)` ≈ #ffffff | Cards, inputs, result panels |
| `--surface-2` | `oklch(96% 0.004 85)` ≈ #f5f2ed | Secondary surfaces |
| `--surface-3` | `oklch(93% 0.005 85)` ≈ #ede8e0 | Hover states |
| `--border` | `oklch(88% 0.007 85)` ≈ #e0d9ce | Separators |
| `--border-light` | `oklch(84% 0.008 85)` ≈ #d5cdc0 | Dashed borders |
| `--accent` | `oklch(53% 0.13 60)` ≈ #b06820 | Primary buttons |
| `--accent-h` | `oklch(48% 0.13 60)` ≈ #8b5e2a | Button hover |
| `--accent-text` | `oklch(44% 0.11 60)` ≈ #8b5e2a | Active tab text |
| `--text` | `oklch(20% 0.006 85)` ≈ #2c2416 | Body text |
| `--text-muted` | `oklch(45% 0.007 85)` ≈ #6b5e4a | Secondary text |
| `--text-dim` | `oklch(65% 0.006 85)` ≈ #a89880 | Placeholders |
| `--success` | `oklch(52% 0.12 145)` ≈ #4a8a5a | Success |
| `--error` | `oklch(50% 0.15 25)` ≈ #c05050 | Error |

### Accent strategy note

Amber-copper was chosen over blue (the "AI tool" reflex), green (the "media app" reflex), or purple (the "dev tool" reflex). It passes the category-reflex check: nothing about "video transcription" implies warm amber. The warmth is intentional — transcripts are long-form text, and warm neutrals create a reading environment closer to paper than to a terminal.

## Typography

### Font stack
```
-apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif
```
System fonts with Inter fallback. One family for everything. Product surface doesn't need display/body pairing.

### Scale
| Role | Size | Weight | Line-height |
|------|------|--------|-------------|
| Page title (h1) | 1.6rem – 2.2rem (clamp) | 740 | 1.15 |
| Section heading (h2) | 1.15rem | 650 | 1.3 |
| Body text | 14px / 0.875rem | 400 | 1.6 – 1.8 |
| Tab / button text | 13–15px | 500–650 | 1 |
| Small / meta text | 10.5–12.5px | 400–500 | 1 |
| Labels (uppercase) | 10.5px | 650 | 1 |

Scale ratio between steps: ≈1.2. Tight enough for product density, enough contrast for hierarchy.

### Line length
- Prose content (transcripts, summaries): capped at 720px container width → ~65–75 characters.
- The `max-width: 720px` on `.main` and `.tab-nav` enforces this naturally.

## Spacing & Rhythm

| Token | Value | Usage |
|-------|-------|-------|
| `--r` | 12px | Card border-radius |
| `--r-sm` | 8px | Input/button border-radius |

Spacing rhythm (vertical): 8px base unit. Common values: 8, 10, 12, 14, 16, 20, 24, 36, 48, 64, 80px. Not every gap is 8px — rhythm comes from intentional variation, not rigid multiples.

- Section gaps: 36–48px
- Component gaps: 12–16px
- Tight gaps (icon + label): 6–8px
- Input padding: 13px 14px (vertical alignment tuned to font metrics, not pure scale)

## Components

### Buttons
- **Primary (`.btn-go`)**: Solid accent background, white text, 10px radius, 13px vertical padding. Used for the main CTA on each page.
- **Secondary (`.icon-btn`, `.btn-fetch`, `.btn-dl`, `.btn-copy-pane`, `.btn-upload-pill`)**: Surface-2 background, border, muted text. Pill-shaped for toolbar actions, rounded-rect for content actions.
- **Small (`.btn-sm`)**: Compact for list-item actions. Surface-3 background, tight padding.
- **Toggle (`.toggle-switch`)**: 40×22px pill with sliding dot. Accent background when checked.
- All buttons have hover, active, disabled, and focus-visible states.

### Inputs
- **Text/URL (`.url-input`, `.s-input`)**: Surface background, 1px border, 10px radius. Focus: accent border + 3px accent box-shadow at 12% opacity. Left icon for URL inputs (link, search, RSS).
- **Select (`.inline-lang-select`, `.s-select`)**: Custom chevron via SVG data-URI background-image. Styled options with surface-2 background.
- **Upload zone (`.upload-zone`)**: Dashed border, surface-2 background. Drag-over: accent border + glow. Click or drop triggers file picker.

### Cards
- **Feed cards, History items**: Surface background, 1px border, 12px radius. Expand inline (no modals). Expanded state: accent-dim border + subtle box-shadow. Expansion animates max-height.
- **Result panel**: Dashed border to distinguish from actionable cards — signals "output area."

### Tabs
- **Top-level nav (`.tab-nav`)**: Border-bottom indicator. Active: accent text + 2px accent bottom-border.
- **Result tabs (`.tab-bar`)**: Same pattern, smaller scale, inside result panel.
- **Download type tabs**: Inline within the detect-results area.

### Progress
- **Progress bar**: 6px height, surface-3 track, accent fill. Width transitions on 500ms ease.
- **Stage pills (`.prog-step`)**: Small rounded pills showing pipeline stages. States: pending (muted), current (accent highlight), done (success dot), skipped (dimmed + strikethrough).
- **Artifact pills (`.artifact-pill`)**: Indicate output file readiness. States: waiting (muted), ready (success tint).

### Empty states
- Icon + single line of text. Centered, generous padding. Teaches the interface: "粘贴链接或上传文件。" ("Paste a link or upload a file.")

## Layout

### Page structure
```
┌─ Navbar (fixed actions: theme, language) ─┐
├─ Tab nav (Transcribe | Download | RSS | History) ─┤
├─ Main (max-width: 720px, centered) ─┤
│  ├─ Page topbar (title + subtitle)        │
│  ├─ Content area                          │
│  └─ Footer                                │
└───────────────────────────────────────────┘
```

Single-column, centered, 720px max-width. No sidebar. Four pages share the same shell via tab navigation. This is intentionally simple — the tool doesn't need multi-column layout.

### Responsive behavior
- Below 560px: input row stacks vertically, settings grid goes single-column, history toolbar collapses.
- The 720px container naturally fits tablets and phones in portrait.
- No fluid typography below the page title. Body text stays at 14px.

## Motion

- Transitions: 150–300ms. Color changes 200ms, border-color 200ms, max-height 300ms ease-out.
- Settings expand/collapse: max-height transition + chevron rotation (250ms).
- Button active: `transform: scale(0.98)` — instant press feedback.
- Progress bar fill: 500ms ease on width.
- Spinner: 700ms linear infinite rotation.
- No page-load animations. No staggered reveals. No spring physics.

## Interaction Optimization Strategy

The current design has a solid foundation. These targeted improvements will reduce UX operation paths and improve readability:

### 1. Reduce operation path depth
- **Problem**: Settings require expand → scroll → find model → fetch. RSS feed management requires navigate → add → refresh → expand → click action.
- **Direction**: Persistent settings state (already done — localStorage saves settings). Pre-fill last-used model. One-click "summarize all new" for RSS. Batch operations on history (already has select mode — make it discoverable).

### 2. Improve content readability
- **Problem**: Markdown content in tab-pane-scroll at 14px/1.8 line-height is good but the 720px container is near the upper end of readable line length. On wide screens, the centered column feels narrow.
- **Direction**: Keep 720px for prose. Increase to 860px for the result panel on screens ≥900px. Slightly larger type (14px → 15px) for transcript body.

### 3. Surface status earlier
- **Problem**: Progress panel hides the empty state only after processing starts. Users clicking "Transcribe" get a brief flash of nothing before the progress bar appears.
- **Direction**: Show a skeleton/anticipation state immediately on submit, before the first SSE event arrives. The smart progress simulation (already in code) handles this — surface it faster.

### 4. Reduce tab friction
- **Problem**: Four top-level tabs for four distinct tools. Users who only transcribe never touch the other three. RSS and History are "list pages" with different layout behavior.
- **Direction**: Keep the tab structure (it's proven and discoverable). Improve the list-page layout stability — the `list-page-active` body class already handles this. Make tab transitions instant (no animation — content swap should feel like a state change, not a page load).

### 5. One-click results access
- **Problem**: After transcription completes, the user sees result tabs. To download, they click a small button in the top-right of the result panel. The download buttons compete with Copy and Retry.
- **Direction**: Group actions by intent: "Export" (download transcript, summary, translation) and "Refine" (retry, copy). Visual grouping via a subtle separator or spacing cluster.

### 6. Empty state as onboarding
- **Problem**: The empty state says "粘贴链接或上传文件。" but doesn't hint at the supported platforms or the workflow.
- **Direction**: Add a one-line hint below the empty state icon listing supported platforms ("YouTube, Bilibili, TikTok, Podcasts, and 30+ more"). Not a tutorial — just enough to signal capability.
