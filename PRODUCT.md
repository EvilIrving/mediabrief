# Product

## Register

MediaBrief

## Users

Content consumers, researchers, learners, and podcast listeners who need text versions of audio/video content. They paste a link or drop a file, wait seconds to minutes, and leave with a readable transcript and AI summary.

Their context: at a desk, often multitasking. They might be studying, researching, preparing content, or catching up on podcasts. Speed matters. The tool should feel like a fast pipeline — input goes in, results come out, friction is invisible.

Secondary users: RSS power users who subscribe to feeds and batch-summarize episodes.

## Product Purpose

Transform any video, audio, or podcast link (from 30+ platforms) into an optimized transcript and AI summary. Make the pipeline feel instant even when it's not — summaries stream in first, transcripts refine in the background. The tool earns trust through speed, not through decoration.

Success: a user pastes a link, reads a summary within seconds (subtitle mode) to single-digit minutes (Whisper mode), and leaves with usable Markdown files. They don't think about the UI at all.

## Brand Personality

**Efficient, capable, unobtrusive.** Three words. Like a sharp chef's knife or a well-balanced hammer — it does the job, feels solid, and never calls attention to itself. The personality is confidence through competence, not through boldness.

Tone: direct, technical but not cold. No marketing superlatives. No emoji overuse. Instructions are clear and brief. Error messages are helpful, not apologetic.

## Anti-references

- **Flashy AI demo products** — gradient-heavy, animated text generation, "magic ✨" everywhere. This tool is a utility, not a tech demo.
- **Over-designed SaaS dashboards** — sidebars with nested nav, metric cards with sparklines, empty-state illustrations that look like stock art. The tool is simpler than a dashboard.
- **Consumer media apps** — large hero images, carousels, social-sharing buttons. This is a work tool.
- **Terminal-only CLI tools** — too cold, too inaccessible for casual users who just want a summary.

## Design Principles

1. **Speed-first perception.** Every visual choice should make the tool feel faster than it is. Progress shows immediately. Summaries stream before transcripts finish. Buttons respond on press, not on release. No loading states sit idle.

2. **Progressive disclosure.** Settings are collapsed by default. Advanced options (two-step summary, model selection) live behind a toggle. The primary path — paste link, pick language, press go — is always visible and obvious.

3. **Content is the interface.** The transcript and summary are the most important things on screen. Chrome (tabs, buttons, borders) serves the content, not the other way around. When results are showing, they dominate the viewport.

4. **Zero-friction input.** URL paste and file drop are equally prominent. No mode-switching between URL and file. The upload zone is always visible, always ready. The form works on Enter. No unnecessary fields.

5. **Consistency without monotony.** Shared component vocabulary across all four pages (Transcribe, Download, RSS, History). Same button shapes, same input styles, same spacing rhythm. Variation comes from content density, not from component reinvention.

## Accessibility & Inclusion

- Target: WCAG 2.1 AA minimum.
- All interactive elements keyboard-accessible with visible focus rings.
- Focus-visible styles use box-shadow, not outline, to stay within the design system.
- Multi-language UI (EN, ZH, JA, KO) with RTL-capable layout for Arabic summaries.
- Dark and light themes both respect `prefers-reduced-motion`.
- Error states are announced (error banner scrolls into view, messages are clear and actionable).
- Form labels are always visible, not placeholder-only.
