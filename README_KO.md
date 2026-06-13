<div align="center">

# AI Video Transcriber

[English](README.md) | [中文](README_ZH.md) | [日本語](README_JA.md) | 한국어

YouTube, Bilibili, TikTok, Apple Podcasts 등 30개 이상 플랫폼 링크를 붙여넣거나, 로컬 오디오·동영상·텍스트 파일을 드롭하세요. 자막이 있으면 그대로 추출하고, 없으면 Whisper로 전사한 뒤 LLM이 텍스트를 정리하고 요약합니다. RSS 자동화도 내장되어 있습니다.

![Screenshot 1](SCR-20260610-mbvm-2.png)
![Screenshot 2](SCR-20260610-jnzj.png)
![Screenshot 3](SCR-20260610-jodn.png)

</div>

## ✨ 주요 기능

- 멀티 플랫폼: YouTube, TikTok, Bilibili, Apple Podcasts, SoundCloud 등 30개 이상 플랫폼
- 로컬 파일: `.mp3`, `.mp4`, `.m4a`, `.wav`, `.webm`, `.mkv`, `.ogg`, `.flac`, 또는 `.txt`（전사 건너뛰고 바로 요약）. 미디어는 FFmpeg로 정규화 후 Whisper 처리
- 자막 우선: 자막이 있으면 오디오 다운로드 없이 즉시 추출. 없으면 Whisper로 전환. 대부분의 YouTube 영상이 이 빠른 경로에 해당
- Whisper 대체: 자막이 없을 때 Faster-Whisper（CTranslate2）로 음성 인식
- LLM 텍스트 정리: 설정된 LLM으로 오타 수정, 문장 완성, 단락 구분
- 다국어 요약: 10개 이상 언어, 원문과 요약 언어가 다르면 자동 번역
- 요약 먼저 제공: 요약은 텍스트 최적화와 병렬 처리되어 전체 내용을 기다리지 않고 먼저 읽을 수 있음
- 2단계 요약（선택）: LLM이 먼저 요약용 프롬프트를 생성한 후 최종 요약 작성. 긴 콘텐츠에 효과적
- 재처리 없는 재시도: 저장된 원본 텍스트로 요약과 최적화 텍스트 재생성. 재다운로드·재전사 불필요
- 다국어 UI: English, 中文, 日本語, 한국어
- 라이트 / 다크 테마: 원클릭 전환
- 모델 직접 설정: OpenAI 호환 API（OpenAI, OpenRouter, 로컬 LLM 등）를 UI에서 설정. API Base URL과 Key 입력 후 Fetch로 모델 목록 불러와 선택
- 통합 작업 대기열: 붙여넣은 링크, 업로드한 파일, 다운로드, RSS 항목——모든 작업이 홈 화면의 단일 대기열로 모여 하나씩 실행됩니다. 진행 상황을 실시간 확인하고, 완료 결과를 열어 보고, 항목을 취소할 수 있으며 같은 작업을 여러 번 대기열에 넣을 수 있습니다
- RSS 구독: 피드 구독, 항목 새로고침, 원클릭 요약 또는 다운로드
- 미디어 다운로드: 사용 가능한 동영상·오디오·자막 형식 감지 및 다운로드
- 서버 기록: 모든 요약이 백엔드 SQLite에 자동 저장. 기록 탭에서 검색·소스 필터·관리
- 모바일 지원: 반응형 레이아웃

## 🚀 빠른 시작

### 사전 요구사항

- Python 3.8+
- FFmpeg（yt-dlp 오디오 추출 및 로컬 미디어 정규화에 필요）
- OpenAI 호환 제공자의 API 키 — UI에서 설정 가능（`.env` 불필요）

### 설치

#### 방법 1: 자동 설치

```bash
git clone git@github.com:EvilIrving/ai-transcriber.git
cd ai-transcriber
chmod +x install.sh
./install.sh
```

#### 방법 2: Docker

```bash
git clone git@github.com:EvilIrving/ai-transcriber.git
cd ai-transcriber

# Docker Compose（권장）
docker-compose up -d

# 또는 수동 빌드
docker build -t ai-transcriber .
docker run -p 8000:8000 ai-transcriber
```

이미지는 **Python 3.12**（Debian Bookworm）기반이며 ffmpeg와 `requirements.txt` 의존성이 사전 설치되어 있습니다.

#### 방법 3: 수동 설치

```bash
# 가상 환경 생성 및 활성화（PEP 668）
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# FFmpeg 설치
brew install ffmpeg          # macOS
sudo apt install ffmpeg       # Debian / Ubuntu
sudo yum install ffmpeg       # RHEL / CentOS
```

### 서비스 시작

```bash
source venv/bin/activate

# 서비스 시작（브라우저 모드）
python3 start.py --no-window

# 또는 데스크톱 모드（pywebview 필요）
python3 start.py
```

브라우저에서 **`http://localhost:8000`** 을 엽니다.

> **데스크톱 모드**: `pywebview` 설치 시 `python3 start.py`가 네이티브 데스크톱 창을 엽니다. `--no-window` 또는 `--server`로 브라우저 전용 모드.

> UI는 `static/dist/`의 사전 빌드된 React 번들에서 제공됩니다（저장소에 동봉）. 앱을 **실행**하는 데 Node.js는 필요 없습니다.

### 프론트엔드 개발

웹 UI는 `frontend/`의 React + TypeScript SPA입니다. UI를 **수정**할 때만 필요합니다:

```bash
cd frontend
pnpm install

# 프로덕션 빌드 → static/dist/로 출력（이후 start.py 실행）
pnpm build

# 또는 HMR 개발 서버（/api를 :8000의 FastAPI로 프록시）
pnpm dev
```

## 📖 사용 가이드

1. **입력 선택 — URL 또는 파일**
   - **URL**: YouTube, Bilibili 등 지원 플랫폼 링크를 붙여넣기
   - **로컬 파일**: 점선 업로드 영역에 드래그하거나 클릭하여 선택. `.txt` 파일은 전사를 건너뛰고 바로 요약 생성
2. **요약 언어 선택**: 드롭다운에서 출력 언어 선택
3. **（선택）AI 모델 설정**: **Settings**를 클릭하여 모델 패널 확장
   - **API Base URL**과 **API Key** 입력
   - **Fetch**를 클릭하여 모델 목록 불러오기
   - 모델 선택（비워두면 서버 기본값 사용）
4. **처리 시작**: **Transcribe** 클릭. 진행 표시줄에 현재 모드가 표시됩니다:
   - **⚡ Subtitle**（녹색）— 자막 발견, 수 초 내 추출 완료
   - **🎙 Whisper**（황색）— 자막 없음, 오디오 다운로드 후 전사
5. **요약 먼저 읽기**: LLM 완료 즉시 요약이 표시됩니다. 전체 전사는 백그라운드에서 계속 최적화
6. **결과 확인**: 최적화된 전사, 번역（언어가 다르면 자동 생성）, 요약 확인
7. **필요 시 재시도**: **Retry** 클릭으로 저장된 원본 텍스트에서 다른 모델이나 언어로 요약 및 전사 재생성
8. **기록 탐색**: **History** 탭을 열어 SQLite에 저장된 과거 요약 검색 및 관리
9. **RSS 자동화**: **RSS** 탭을 열고 피드 구독, 항목 새로고침, 원클릭 요약 또는 다운로드. 대기열에 추가된 작업은 **Transcribe** 탭의 통합 대기열에서 실행되며 거기서 진행 상황 확인과 취소가 가능합니다（RSS 탭 자체는 대기열에 추가만 함）
10. **미디어 다운로드**: **Download** 탭을 열고 형식을 감지하여 동영상·오디오·자막 파일 다운로드
11. **생성 파일 저장**: Markdown 형식의 전사·번역·요약 파일 저장

## 🛠️ 기술 아키텍처

### 백엔드 스택
- **FastAPI** — SSE 스트리밍 지원 비동기 웹 프레임워크
- **yt-dlp** — 1,800개 이상 사이트에서 동영상·오디오·자막 추출
- **FFmpeg** — 오디오 정규화（Whisper용 모노 16 kHz）
- **Faster-Whisper** — CTranslate2 가속 음성 인식
- **OpenAI SDK** — 호환 API를 통한 요약 생성, 전사 최적화, 번역

### 프론트엔드 스택
- **React + TypeScript** — 컴포넌트화된 SPA, 클라이언트 사이드 라우팅（React Router, `HashRouter`）
- **Vite** — 빌드 도구; `static/dist/`로 출력되어 FastAPI가 제공
- **Tailwind CSS v4** — 기존 oklch 디자인 토큰 위에 얹은 유틸리티 스타일（라이트/다크 테마）
- **Marked** — 클라이언트 사이드 Markdown 렌더링
- **인라인 SVG 아이콘** — Lucide 심볼 스프라이트（아이콘 폰트 의존성 없음）

### 프로젝트 구조

```
ai-transcriber/
├── backend/                     # 백엔드 코드
│   ├── main.py                 # FastAPI 앱 어셈블리, 미들웨어, 라우트 등록
│   ├── services.py             # 공유 싱글톤 인스턴스（프로세서, 업로드 설정）
│   ├── pipeline.py             # 오케스트레이션 계층: 추출 후 파이프라인, 작업 실행
│   ├── task_store.py           # 작업 상태 머신, 단계 가중치, SSE 브로드캐스트
│   ├── video_processor.py      # yt-dlp 래퍼: 다운로드, 형식 감지, 자막 가져오기
│   ├── transcriber.py          # Faster-Whisper 전사
│   ├── summarizer.py           # LLM 요약 생성（1단계·2단계）
│   ├── translator.py           # LLM 기반 번역（언어 감지 포함）
│   ├── exporter.py             # 다중 형식 내보내기 엔진（MD/TXT/DOCX/PDF）
│   ├── llm_sanitize.py         # 모델 출력에서 LLM 상용구 제거
│   ├── db.py                   # SQLite 데이터베이스 계층（작업·기록·RSS）
│   ├── rss_reader.py           # RSS/Atom 피드 파서（SQLite 영속화）
│   └── routers/
│       ├── __init__.py
│       ├── core.py             # 정적 페이지 제공, 모델 목록 프록시, 헬스 체크
│       ├── transcribe.py       # URL/업로드 처리, 작업 상태, SSE, 재시도
│       ├── downloads.py        # 동영상/오디오/자막 다운로드 엔드포인트
│       ├── export.py           # 전사/요약/번역을 MD/TXT/DOCX/PDF로 내보내기
│       └── rss.py              # RSS 구독, 항목 목록, 작업 생성
├── frontend/                   # React + TypeScript SPA（소스）
│   ├── src/
│   │   ├── main.tsx            # 진입점
│   │   ├── App.tsx             # Providers + HashRouter + 페이지 라우트
│   │   ├── index.css          # 디자인 토큰 + 이식된 컴포넌트 스타일 + Tailwind
│   │   ├── lib/               # api.ts, types.ts, markdown.ts
│   │   ├── context/          # Theme, Settings, TaskHandoff 프로바이더
│   │   ├── i18n/             # UI 언어 사전 및 프로바이더
│   │   ├── components/       # Navbar, Footer, IconSprite, ErrorBanner, Markdown
│   │   └── features/         # transcribe / download / rss / history 페이지
│   ├── vite.config.ts         # base=/static/dist/, outDir=../static/dist, /api 프록시
│   └── package.json
├── static/                     # FastAPI가 제공
│   ├── dist/                   # 빌드된 SPA（pnpm build 출력, 사용자에게 동봉）
│   ├── icon_dark.svg           # 앱 아이콘
│   └── index.html              # 레거시 Vanilla JS UI（폴백 전용）
├── scripts/
│   ├── build_macos.sh          # macOS .app 빌드 스크립트
│   ├── build_windows.ps1       # Windows .exe 빌드 스크립트
│   └── sign_and_package.sh     # macOS 서명·공증·DMG 패키징
├── pyinstaller/
│   └── ai_transcriber.spec     # PyInstaller 빌드 설정
├── temp/                       # SQLite DB + 임시 파일（전사, 요약, 다운로드）
├── Dockerfile                  # Python 3.12 slim-bookworm 이미지
├── docker-compose.yml          # 리소스 제한 포함 Docker Compose
├── .dockerignore
├── requirements.txt            # Python 의존성（하한 고정）
├── install.sh                  # 원스텝 설치기（macOS/Linux）
├── install.ps1                 # 원스텝 설치기（Windows PowerShell）
├── install.bat                 # 원스텝 설치기（Windows CMD）
├── start.py                    # 시작 스크립트: uvicorn 서버 + pywebview 데스크톱 창
├── start.bat                   # Windows 빠른 시작
├── podcast_rss_feeds.md        # 큐레이션된 팟캐스트 RSS 피드 모음
├── recommended_rss_feeds.json  # 가져오기용 RSS 피드 목록
└── README_KO.md                # 이 파일
```

## ⚙️ 설정 옵션

### 앱 내 설정

API Base URL, API 키, 모델, 요약 언어, 2단계 요약은 UI의 **Settings** 패널에서 설정합니다. 백엔드는 모델/API 설정을 위해 `.env` 또는 환경 변수 fallback을 읽지 않습니다.

### Whisper 모델 크기

| 모델 | 파라미터 | 다국어 | 속도 | 메모리 |
|-------|--------|-------------|-------|--------|
| tiny | 39 M | ✓ | 빠름 | ~150 MB |
| base | 74 M | ✓ | 중간 | ~250 MB |
| small | 244 M | ✓ | 중간 | ~750 MB |
| medium | 769 M | ✓ | 느림 | ~1.5 GB |
| large | 1550 M | ✓ | 매우 느림 | ~3 GB |

## 🔧 자주 묻는 질문

### Q: 왜 전사보다 요약이 먼저 표시되나요?
A: 파이프라인이 요약을 전사 최적화와 병렬로 생성합니다. 요약은 가볍게 정리된 원본 텍스트만 필요하므로 전체 전사 최적화를 기다리지 않고 빠르게 완료됩니다.

### Q: 동영상 전체를 재처리하지 않고 모델이나 언어를 변경할 수 있나요?
A: 네. **Retry** 버튼으로 저장된 원본 전사에 대해 최적화+요약 단계만 재실행할 수 있습니다. 재다운로드·재전사 불필요.

### Q: '2단계 요약' 옵션이 무엇인가요?
A: 활성화하면 LLM이 먼저 콘텐츠와 대상 언어에 기반한 요약 프롬프트를 생성한 후, 그 프롬프트로 최종 요약을 작성합니다. 긴 콘텐츠나 복잡한 내용에서 더 구조화된 결과를 얻는 경우가 많습니다.

### Q: 지원하는 플랫폼은?
A: yt-dlp가 지원하는 모든 플랫폼 — YouTube, TikTok, Facebook, Instagram, Twitter/X, Bilibili, Youku, iQiyi, Tencent Video 등 1,800개 이상.

### Q: 지원하는 파일 형식과 크기 제한은?
A: `.txt`, `.mp3`, `.mp4`, `.m4a`, `.wav`, `.webm`, `.mkv`, `.ogg`, `.flac`. 기본 최대 크기는 **200 MB**.

### Q: AI 모델은 어떻게 설정하나요?
A: UI의 **Settings** 패널을 열고 API Base URL과 API Key를 입력한 후 **Fetch**를 클릭하여 사용 가능한 모델을 불러와 선택합니다. 서버 재시작은 필요하지 않습니다.

### Q: 개발 모드에서 Ctrl+C가 작동하지 않거나 재시작 시 'Address already in use' 오류가 발생하나요?
A: `concurrently` + `uvicorn --reload`에서 흔한 문제입니다.
- `pnpm stop`을 실행하여 8000/5173 포트 강제 해제
- Ctrl+C가 멈추는 경우 Whisper 사전 로드 스레드가 프로세스를 유지 중일 수 있습니다 — `pnpm stop` 사용
- 개발 스크립트는 `temp/*`를 파일 감시에서 제외하므로 마이그레이션 bak 파일 생성으로 인한 재로드 루프가 발생하지 않습니다

### Q: YouTube에서 'Sign in to confirm you're not a bot' 오류가 발생하나요?
A: yt-dlp에 JS 챌린지 솔버가 내장되어 있습니다. **Deno** 또는 **Node.js**가 설치되어 있는지 확인하세요: `brew install deno`（macOS）또는 `apt install nodejs`（Debian/Ubuntu）.

### Q: HTTP 500 오류가 발생하는 이유는?
A: 다음을 확인하세요:
- 가상 환경이 활성화되어 있는지: `source venv/bin/activate`
- 의존성이 설치되어 있는지: `pip install -r requirements.txt`
- FFmpeg가 설치되어 있는지: `ffmpeg -version`
- API Base URL, API 키, 모델이 UI Settings 패널에서 설정되어 있는지
- 포트 8000이 사용 중이 아닌지

### Q: Docker 사용법은?
A:
```bash
docker-compose up -d

# 로그 확인
docker logs ai-video-transcriber-ai-video-transcriber-1

# 중지
docker-compose down

# 코드 변경 후 재빌드
docker-compose build --no-cache && docker-compose up -d
```

### Q: 메모리 요구사항은?
A:
- **Docker 유휴 시**: ~128 MB
- **Docker 처리 시**: 500 MB – 2 GB（모델 의존）
- **일반 배포 유휴 시**: ~50–100 MB
- **처리 피크 시**: 기본 + Whisper 모델 + 동영상 처리용 ~500 MB
- **권장**: 4 GB 이상 RAM. 메모리가 부족하면 `tiny` 또는 `base` 모델 사용

## 🖥️ macOS 데스크톱 앱

```bash
# 1회성 환경 설정
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt pyinstaller pywebview
brew install librsvg

# 빌드
bash scripts/build_macos.sh

# 실행（최초 실행 시 Whisper 모델 ~250 MB 다운로드）
open "dist/AI Transcriber.app"

# API 키 / 모델 설정
# 실행 후 앱의 AI Settings 패널에서 설정

# 서명 및 공증（배포용, Apple Developer ID 필요）
bash scripts/sign_and_package.sh notarize
```

> **첫 실행 팁**: 터미널에서 실행 — `"dist/AI Transcriber.app/Contents/MacOS/ai-transcriber"`. 프로세스 폭증 시 `pkill -9 -f ai-transcriber` 후 재빌드.

## 🎯 지원 언어

### 전사
Whisper를 통한 100개 이상 언어 — 자동 언어 감지, 주요 언어에서 높은 정확도.

### 요약 언어
English, 中文（간체）, 日本語, 한국어, Español, Français, Deutsch, Português, Русский, العربية 등.

## 📈 성능 예상

| 동영상 길이 | 자막 모드 | Whisper 모드 | 비고 |
|-------------|---------------|--------------|-------|
| 1분 | ~5초 | 30초 – 1분 | 자막 모드는 다운로드 불필요 |
| 5분 | ~10초 | 2 – 5분 | 대부분의 YouTube 동영상은 자막 모드 |
| 15분 | ~15초 | 5 – 15분 | 두 모드 모두 요약이 먼저 표시 |
| 30분 이상 | ~20초 | 15 – 60분 | 팟캐스트는 항상 Whisper |

## 🤝 기여하기

Issue와 Pull Request를 환영합니다!

1. 프로젝트 포크
2. 기능 브랜치 생성（`git checkout -b feature/AmazingFeature`）
3. 변경사항 커밋（`git commit -m 'Add AmazingFeature'`）
4. 브랜치 푸시（`git push origin feature/AmazingFeature`）
5. Pull Request 생성

## 감사의 글

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — 유니버설 동영상/오디오 추출기
- [Faster-Whisper](https://github.com/guillaumekln/faster-whisper) — CTranslate2 가속 Whisper
- [FastAPI](https://fastapi.tiangolo.com/) — 모던 비동기 Python 웹 프레임워크
- [OpenAI](https://openai.com/) — 요약 및 텍스트 최적화를 위한 LLM API

## 📞 문의

질문이나 제안은 Issue를 생성해 주세요.

---

## ⭐ 스타 기록

이 프로젝트가 유용했다면 스타를 부탁드립니다!
