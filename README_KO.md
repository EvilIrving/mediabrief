<div align="center">

# AI Video Transcriber

[English](README.md) | [中文](README_ZH.md) | [日本語](README_JA.md) | 한국어

동영상과 팟캐스트를 전사, 번역, 요약하고 기록으로 저장하는 오픈소스 도구입니다. YouTube, Bilibili, TikTok, Apple Podcasts, SoundCloud 등 30개 이상의 플랫폼 URL과 로컬 오디오·동영상·텍스트 파일을 지원합니다.

![Interface](en_video.png)

</div>

## ✨ 주요 기능

- 🎥 YouTube / Bilibili / TikTok / Podcast 등 30개 이상 플랫폼 지원
- 📁 로컬 업로드: `.txt`, `.mp3`, `.mp4`, `.m4a`, `.wav`, `.webm`, `.mkv`, `.ogg`, `.flac`
- ⚡ 자막 우선 처리: 자막이 있으면 오디오 다운로드 없이 빠르게 처리하고, 없으면 Faster-Whisper로 전환
- 🤖 OpenAI 호환 API를 통한 텍스트 최적화, 번역, 요약
- 🌍 요약 언어 선택과 조건부 번역
- 🌐 UI 언어: English / 中文 / 日本語 / 한국어
- 🗂️ IndexedDB 요약 기록: History 탭에서 온라인 조회, 검색, 삭제
- 📡 RSS: 피드 구독, 새로고침, 항목별 요약/다운로드 작업 생성
- ⬇️ Download 탭: 동영상, 오디오, 자막을 감지하고 다운로드

## 🚀 빠른 시작

```bash
git clone git@github.com:EvilIrving/ai-transcriber.git
cd ai-transcriber
chmod +x install.sh
./install.sh
python3 start.py --prod
```

Docker 사용:

```bash
cp .env.example .env
docker-compose up -d
```

필요 항목: Python 3.8+, FFmpeg, OpenAI 호환 제공자의 API Key(UI의 AI Settings에서 설정 가능).

## 📖 사용 방법

1. Transcribe 탭에서 URL을 붙여넣거나 로컬 파일을 업로드합니다.
2. 요약 언어를 선택하고, 필요하면 AI Settings에서 API Base URL / API Key / Model을 설정합니다.
3. **Transcribe**를 클릭합니다.
4. Transcript / AI Summary / Translation을 화면에서 확인합니다.
5. History 탭에서 저장된 요약을 검색, 조회, 삭제할 수 있습니다.
6. RSS 탭에서 피드를 구독하고 각 항목의 요약 또는 다운로드 작업을 만들 수 있습니다.
7. Download 탭에서 동영상·오디오·자막 파일을 저장할 수 있습니다.

## 🧩 프론트엔드 구조

```text
static/
├── index.html
├── app.js              # 초기화 및 모듈 연결
└── js/
    ├── i18n.js         # UI 번역 사전과 i18n 헬퍼
    ├── ui.js           # 테마, 설정, 복사/다운로드 보조 기능
    ├── transcribe.js   # 전사 작업과 SSE 처리
    ├── download.js     # 동영상/오디오/자막 다운로드
    ├── history.js      # IndexedDB 요약 기록
    └── rss.js          # RSS 구독과 작업 동작
```

## 라이선스

MIT License
