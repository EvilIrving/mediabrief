# Media assets for README

| File | Role |
|------|------|
| `home.png` | Transcribe page screenshot |
| `rss.png` | RSS page screenshot |
| `history.png` | History page screenshot |
| `demo.mp4` | Product demo video (linked from all README language variants) |

## Drop in a new demo video

1. Export a short clip (aim **under ~25 MB**, ideally 15–45 s; H.264 + AAC in `.mp4`).
2. Save it exactly as:

   ```text
   docs/img/demo.mp4
   ```

3. Commit and push (this path is **not** gitignored; general `*.mp4` still is).

After push to `main`, the README embeds this absolute URL so visitors can play it on GitHub:

```text
https://github.com/EvilIrving/mediabrief/raw/main/docs/img/demo.mp4
```

Optional: also add `docs/img/demo.webm` for a smaller alternate; the README primary link is the `.mp4`.
