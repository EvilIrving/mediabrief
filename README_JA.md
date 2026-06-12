<div align="center">

# AI Video Transcriber

[English](README.md) | [中文](README_ZH.md) | 日本語 | [한국어](README_KO.md)

YouTube、Bilibili、TikTok、Apple Podcasts など 30+ プラットフォームのリンクを貼るか、ローカルの音声・動画・テキストファイルをドロップしてください。字幕がある場合はそのまま抽出し、なければ Whisper で文字起こし、LLM でテキストを整えて要約します。RSS による定期処理も内蔵しています。

![Screenshot 1](SCR-20260610-mbvm-2.png)
![Screenshot 2](SCR-20260610-jnzj.png)
![Screenshot 3](SCR-20260610-jodn.png)

</div>

## ✨ 主な機能

- マルチプラットフォーム: YouTube、TikTok、Bilibili、Apple Podcasts、SoundCloud など 30+ プラットフォーム
- ローカルファイル: `.mp3`, `.mp4`, `.m4a`, `.wav`, `.webm`, `.mkv`, `.ogg`, `.flac`、または `.txt`（文字起こしをスキップして要約へ直行）。メディアは FFmpeg で正規化してから Whisper へ
- 字幕優先: 字幕があれば音声ダウンロードなしで即抽出。なければ Whisper にフォールバック。ほとんどの YouTube 動画がこの高速パスに該当
- Whisper フォールバック: 字幕がない場合、Faster-Whisper（CTranslate2）で文字起こし
- LLM テキスト整形: 設定した LLM による誤字修正、文章補完、段落分け
- 多言語要約: 10+ 言語対応、原文と要約言語が異なる場合は自動翻訳
- 要約を先に表示: 要約はテキスト最適化と並行処理されるため、全文の処理を待たずに要約を読める
- 2段階要約（オプション）: LLM がまず要約用プロンプトを生成し、それを使って最終要約を作成。長いコンテンツで効果的
- 再処理なしリトライ: 保存済みの生テキストから要約と最適化テキストを再生成。再ダウンロード・再文字起こし不要
- 多言語 UI: English、中文、日本語、한국어
- ライト / ダークテーマ: ワンクリック切替
- モデル持ち込み: OpenAI 互換 API（OpenAI、OpenRouter、ローカル LLM など）を UI から設定。API Base URL と Key を入力し、Fetch でモデル一覧を取得して選択
- RSS 購読: フィード購読、エントリ更新、ワンクリックで要約またはダウンロード
- メディアダウンロード: 利用可能な動画・音声・字幕フォーマットを検出してダウンロード
- 複数形式でエクスポート: MD、TXT、DOCX、PDF
- ブラウザ履歴: History タブで過去の要約を検索・展開・削除。IndexedDB 保存、データベースサーバー不要
- モバイル対応: レスポンシブレイアウト

## 🚀 クイックスタート

### 前提条件

- Python 3.8+
- FFmpeg（yt-dlp の音声抽出とローカルメディア正規化に必要）
- OpenAI 互換プロバイダーの API キー — UI から設定可能（`.env` 不要）

### インストール

#### 方法1: 自動インストール

```bash
git clone git@github.com:EvilIrving/ai-transcriber.git
cd ai-transcriber
chmod +x install.sh
./install.sh
```

#### 方法2: Docker

```bash
git clone git@github.com:EvilIrving/ai-transcriber.git
cd ai-transcriber

# Docker Compose（推奨）
cp .env.example .env
# .env を編集して API キーを設定（省略可 — UI からも設定可能）
docker-compose up -d

# または手動ビルド
docker build -t ai-transcriber .
docker run -p 8000:8000 --env-file .env ai-transcriber
```

イメージは **Python 3.12**（Debian Bookworm）ベースで、ffmpeg と `requirements.txt` の依存関係をインストール済みです。

#### 方法3: 手動インストール

```bash
# 仮想環境を作成して有効化（PEP 668）
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# FFmpeg をインストール
brew install ffmpeg          # macOS
sudo apt install ffmpeg       # Debian / Ubuntu
sudo yum install ffmpeg       # RHEL / CentOS
```

### サービスの起動

```bash
source venv/bin/activate

# サービス起動（ブラウザモード）
python3 start.py --no-window

# またはデスクトップモード（pywebview 要）
python3 start.py
```

ブラウザで **`http://localhost:8000`** を開きます。

> **デスクトップモード**: `pywebview` インストール時は `python3 start.py` でネイティブデスクトップ窓が開きます。`--no-window` または `--server` でブラウザ専用モード。

## 📖 使い方

1. **入力を選択 — URL またはファイル**
   - **URL**: YouTube、Bilibili、その他対応プラットフォームのリンクを貼り付け
   - **ローカルファイル**: 点線のアップロード領域にドラッグするか、クリックして選択。`.txt` ファイルは文字起こしをスキップして直接要約生成へ
2. **要約言語を選択**: ドロップダウンから出力言語を選択
3. **（オプション）AI モデルを設定**: **Settings** をクリックしてモデルパネルを展開
   - **API Base URL** と **API Key** を入力
   - **Fetch** をクリックしてモデル一覧を取得
   - モデルを選択（空白のままにするとサーバー既定値を使用）
4. **処理を開始**: **Transcribe** をクリック。プログレスバーに現在のモードが表示されます:
   - **⚡ Subtitle**（緑）— 字幕が見つかり、数秒で抽出完了
   - **🎙 Whisper**（琥珀色）— 字幕なし、音声をダウンロードして文字起こし
5. **要約を先に読む**: 要約は LLM が完了次第すぐ表示されます。全文の文字起こしはバックグラウンドで引き続き最適化
6. **結果を確認**: 最適化された文字起こし、翻訳（言語が異なる場合は自動生成）、要約を確認
7. **必要に応じてリトライ**: **Retry** をクリックすると、保存済みの生テキストから別のモデルや言語で要約と文字起こしを再生成
8. **履歴を閲覧**: **History** タブを開いて、IndexedDB に保存された過去の要約を検索・管理
9. **RSS 自動化**: **RSS** タブを開き、フィードを購読、エントリを更新、ワンクリックで要約やダウンロード
10. **メディアをダウンロード**: **Download** タブを開き、フォーマットを検出して動画・音声・字幕ファイルをダウンロード
11. **結果をエクスポート**: エクスポートボタンで文字起こし・翻訳・要約を Markdown、TXT、DOCX、PDF として保存

## 🛠️ 技術アーキテクチャ

### バックエンドスタック
- **FastAPI** — SSE ストリーミング対応の非同期 Web フレームワーク
- **yt-dlp** — 1,800 以上のサイトから動画・音声・字幕を抽出
- **FFmpeg** — 音声正規化（Whisper 用にモノラル 16 kHz）
- **Faster-Whisper** — CTranslate2 で高速化された音声認識
- **OpenAI SDK** — 互換 API 経由での要約生成、文字起こし最適化、翻訳

### フロントエンドスタック
- **HTML5 + CSS3** — レスポンシブインターフェース、ライト/ダークテーマ対応
- **Vanilla JavaScript (ES6+)** — フレームワーク不要
- **Marked.js** — クライアントサイド Markdown レンダリング（ローカルバンドル、CDN 不要）
- **Font Awesome 6** — アイコンライブラリ（ローカルバンドル、CDN 不要）
- **IndexedDB** — クライアントサイドの要約履歴保存

### プロジェクト構造

```
ai-transcriber/
├── backend/                     # バックエンドコード
│   ├── main.py                 # FastAPI アプリアセンブリ、ミドルウェア、ルート登録
│   ├── services.py             # 共有シングルトンインスタンス（プロセッサ、アップロード設定）
│   ├── pipeline.py             # オーケストレーション層: 抽出後パイプライン、タスク実行
│   ├── task_store.py           # タスクステートマシン、ステージ重み、SSE ブロードキャスト
│   ├── video_processor.py      # yt-dlp ラッパー: ダウンロード、フォーマット検出、字幕取得
│   ├── transcriber.py          # Faster-Whisper 文字起こし
│   ├── summarizer.py           # LLM 要約生成（1段階・2段階）
│   ├── translator.py           # LLM ベース翻訳（言語検出付き）
│   ├── exporter.py             # マルチフォーマットエクスポート（MD/TXT/DOCX/PDF）
│   ├── llm_sanitize.py         # モデル出力からの LLM 定型文除去
│   ├── rss_reader.py           # RSS/Atom フィードパーサー（JSON 永続化）
│   └── routers/
│       ├── __init__.py
│       ├── core.py             # 静的ページ配信、モデルリストプロキシ、ヘルスチェック
│       ├── transcribe.py       # URL/アップロード処理、タスク状態、SSE、リトライ
│       ├── downloads.py        # 動画/音声/字幕ダウンロードエンドポイント
│       ├── export.py           # 文字起こし/要約/翻訳を MD/TXT/DOCX/PDF でエクスポート
│       └── rss.py              # RSS 購読、エントリ一覧、タスク作成
├── static/                     # フロントエンドファイル
│   ├── index.html              # メインページ（CSS 埋め込み）
│   ├── app.js                  # エントリポイント: 初期化、タブ切り替え
│   ├── vendor/
│   │   ├── fontawesome.min.css # Font Awesome 6（ローカルバンドル）
│   │   ├── fa-*.ttf/woff2      # Font Awesome ウェブフォント
│   │   └── marked.min.js       # Markdown レンダラー（ローカルバンドル）
│   └── js/
│       ├── i18n.js             # UI 言語辞書とヘルパー
│       ├── ui.js               # テーマ切替、設定パネル、コピー/ダウンロード補助
│       ├── api.js              # 全バックエンドエンドポイント用 HTTP クライアント
│       ├── transcribe.js       # 文字起こしタスクフロー、SSE ストリーミング、進捗 UI
│       ├── download.js         # ダウンロードページ: フォーマット検出、ダウンロードワークフロー
│       ├── history.js          # IndexedDB ストレージ、検索、削除
│       └── rss.js              # RSS 購読、フィード解析、エントリアクション
├── scripts/
│   ├── build_macos.sh          # macOS .app ビルドスクリプト
│   ├── build_windows.ps1       # Windows .exe ビルドスクリプト
│   └── sign_and_package.sh     # macOS 署名・公証・DMG パッケージ
├── pyinstaller/
│   └── ai_transcriber.spec     # PyInstaller ビルド設定
├── temp/                       # 一時ファイル（文字起こし、要約、ダウンロード）
├── Dockerfile                  # Python 3.12 slim-bookworm イメージ
├── docker-compose.yml          # リソース制限付き Docker Compose
├── .dockerignore
├── .env.example                # 環境変数テンプレート
├── requirements.txt            # Python 依存関係（下限固定）
├── install.sh                  # ワンステップインストーラー（macOS/Linux）
├── install.ps1                 # ワンステップインストーラー（Windows PowerShell）
├── install.bat                 # ワンステップインストーラー（Windows CMD）
├── start.py                    # 起動スクリプト: uvicorn サーバー + pywebview デスクトップ窓
├── start.bat                   # Windows クイック起動
├── podcast_rss_feeds.md        # ポッドキャスト RSS フィードコレクション
├── recommended_rss_feeds.json  # インポート用 RSS フィードリスト
└── README_JA.md                # このファイル
```

## ⚙️ 設定オプション

### 環境変数

| 変数 | 説明 | 既定値 | 必須 |
|----------|-------------|---------|----------|
| `OPENAI_API_KEY` | API キー（サーバー側既定値） | — | 不要 — UI で設定可 |
| `OPENAI_BASE_URL` | OpenAI 互換 API エンドポイント | `https://api.openai.com/v1` | 不要 |
| `HOST` | サーバーバインドアドレス | `0.0.0.0` | 不要 |
| `PORT` | サーバーポート | `8000` | 不要 |
| `WHISPER_MODEL_SIZE` | Whisper モデルサイズ | `base` | 不要 |
| `UPLOAD_MAX_MB` | 最大アップロードサイズ（MB） | `200` | 不要 |
| `LLM_TIMEOUT_SEC` | LLM 呼出タイムアウト（秒） | `300` | 不要 |

### Whisper モデルサイズ

| モデル | パラメータ数 | 多言語 | 速度 | メモリ |
|-------|--------|-------------|-------|--------|
| tiny | 39 M | ✓ | 高速 | ~150 MB |
| base | 74 M | ✓ | 中速 | ~250 MB |
| small | 244 M | ✓ | 中速 | ~750 MB |
| medium | 769 M | ✓ | 低速 | ~1.5 GB |
| large | 1550 M | ✓ | 非常に低速 | ~3 GB |

## 🔧 よくある質問

### Q: なぜ文字起こしより先に要約が表示されるのですか？
A: パイプラインは要約を文字起こし最適化と並行して生成します。要約は軽くクリーニングされた生テキストのみを必要とするため、全文の最適化を待たずに素早く完了します。

### Q: 動画全体を再処理せずにモデルや言語を変更できますか？
A: はい。**Retry** ボタンで、保存済みの生文字起こしに対して最適化＋要約ステップのみを再実行できます。再ダウンロード・再文字起こしは不要です。

### Q: 「2段階要約」オプションとは何ですか？
A: 有効にすると、LLM がまずコンテンツと目的言語に基づいて要約用プロンプトを生成し、そのプロンプトを使って最終要約を作成します。長いコンテンツや複雑な内容でより構造化された結果が得られることが多いです。

### Q: 対応プラットフォームは？
A: yt-dlp がサポートするすべてのプラットフォーム — YouTube、TikTok、Facebook、Instagram、Twitter/X、Bilibili、Youku、iQiyi、Tencent Video など 1,800 以上。

### Q: 対応ファイル形式とサイズ制限は？
A: `.txt`、`.mp3`、`.mp4`、`.m4a`、`.wav`、`.webm`、`.mkv`、`.ogg`、`.flac`。既定の最大サイズは **200 MB**（`UPLOAD_MAX_MB` で変更可）。

### Q: AI モデルの設定方法は？
A: UI の **Settings** パネルを開き、API Base URL と API Key を入力、**Fetch** をクリックして利用可能なモデルを読み込み、選択します。サーバーの再起動は不要です。`.env` に `OPENAI_API_KEY` と `OPENAI_BASE_URL` を設定してサーバー既定値とすることもできます。

### Q: YouTube で「Sign in to confirm you're not a bot」と表示されますか？
A: yt-dlp には JS チャレンジソルバーが組み込まれています。**Deno** または **Node.js** がインストールされていることを確認してください: `brew install deno`（macOS）または `apt install nodejs`（Debian/Ubuntu）。

### Q: HTTP 500 エラーが発生するのはなぜですか？
A: 以下を確認してください:
- 仮想環境が有効化されている: `source venv/bin/activate`
- 依存関係がインストールされている: `pip install -r requirements.txt`
- FFmpeg がインストールされている: `ffmpeg -version`
- API キーが設定されている（UI の Settings パネルまたは `OPENAI_API_KEY` 環境変数）
- ポート 8000 が使用中でない

### Q: Docker の使い方は？
A:
```bash
cp .env.example .env
# .env を編集して API キーを設定（省略可）
docker-compose up -d

# ログの確認
docker logs ai-video-transcriber-ai-video-transcriber-1

# 停止
docker-compose down

# コード変更後に再ビルド
docker-compose build --no-cache && docker-compose up -d
```

### Q: メモリ要件は？
A:
- **Docker アイドル時**: ~128 MB
- **Docker 処理時**: 500 MB – 2 GB（モデル依存）
- **通常デプロイ アイドル時**: ~50–100 MB
- **処理ピーク時**: ベース + Whisper モデル + 動画処理用 ~500 MB
- **推奨**: 4 GB 以上の RAM。メモリが厳しい場合は `tiny` または `base` モデルを使用

## 🖥️ macOS デスクトップアプリ

```bash
# 初回セットアップ
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt pyinstaller pywebview
brew install librsvg

# ビルド
bash scripts/build_macos.sh

# 実行（初回は Whisper モデル ~250 MB をダウンロード）
open "dist/AI Transcriber.app"

# API キー
cp "dist/AI Transcriber.app/Contents/MacOS/.env.example" \
   "dist/AI Transcriber.app/Contents/MacOS/.env"
# .env を編集 → OPENAI_API_KEY=sk-...

# 署名・公証（配布用、Apple Developer ID が必要）
bash scripts/sign_and_package.sh notarize
```

> **初回実行のヒント**: ターミナルから起動 — `"dist/AI Transcriber.app/Contents/MacOS/ai-transcriber"`。プロセスが大量生成されたら `pkill -9 -f ai-transcriber` で停止し再ビルド。

## 🎯 対応言語

### 文字起こし
Whisper による 100 以上の言語 — 自動言語検出、主要言語で高精度。

### 要約言語
English、中文（簡体）、日本語、한국어、Español、Français、Deutsch、Português、Русский、العربية など。

## 📈 パフォーマンス目安

| 動画の長さ | 字幕モード | Whisper モード | 備考 |
|-------------|---------------|--------------|-------|
| 1 分 | ~5 秒 | 30 秒 – 1 分 | 字幕モードはダウンロード不要 |
| 5 分 | ~10 秒 | 2 – 5 分 | ほとんどの YouTube 動画は字幕モード |
| 15 分 | ~15 秒 | 5 – 15 分 | どちらのモードでも要約が先に表示 |
| 30 分以上 | ~20 秒 | 15 – 60 分 | ポッドキャストは常に Whisper |

## 🤝 コントリビューション

Issue や Pull Request を歓迎します！

1. プロジェクトをフォーク
2. フィーチャーブランチを作成（`git checkout -b feature/AmazingFeature`）
3. 変更をコミット（`git commit -m 'Add AmazingFeature'`）
4. ブランチをプッシュ（`git push origin feature/AmazingFeature`）
5. Pull Request を作成

## 謝辞

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — ユニバーサル動画/音声抽出
- [Faster-Whisper](https://github.com/guillaumekln/faster-whisper) — CTranslate2 高速化 Whisper
- [FastAPI](https://fastapi.tiangolo.com/) — モダンな非同期 Python Web フレームワーク
- [OpenAI](https://openai.com/) — 要約とテキスト最適化のための LLM API

## 📞 お問い合わせ

質問や提案は Issue を作成してください。

---

## ⭐ スター履歴

このプロジェクトが役立ったら、スターをお願いします！
