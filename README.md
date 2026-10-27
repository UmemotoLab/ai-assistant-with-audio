# ai-assistant-with-audio

OpenRouter のチャットモデルで応答し、Gemini TTS で読み上げる CLI アシスタントです。
1 回の実行で 1 メッセージを処理します。設計は [implementation-plan.md](implementation-plan.md)、会話フローは [flow.md](flow.md) を参照してください。

## セットアップ

```powershell
uv sync
Copy-Item .env.example .env   # 値を設定する
```

`.env` の項目:

| 変数 | 必須 | 内容 |
|---|---|---|
| `OPENROUTER_API_KEY` | ○ | 対話 LLM 用 |
| `OPENROUTER_CHAT_MODEL` | ○ | 対話 LLM のモデル ID（JSON 応答に対応したもの） |
| `GEMINI_API_KEY` | 音声用 | Gemini TTS 用 |
| `GEMINI_VOICE_ID` | 音声用 | 音声 ID（`--voice-id` で上書き可）。`Kore` などのプリセット名でも動作を確認済み |
| `SESSION_MATCH_THRESHOLD` | 任意 | セッション自動判定の閾値 0〜1（既定 0.5） |

音声が未設定の場合は警告を出し、テキストのみで動作します。音声の再生は Windows（`winsound`）のみ対応です。

## 使い方

```powershell
uv run ai-assistant-with-audio "私の好きな食べ物はラーメンです。覚えておいて。"
uv run ai-assistant-with-audio --new "新しい話題です"          # 強制新規
uv run ai-assistant-with-audio --session <ID> "続きの話です"    # 強制継続
uv run ai-assistant-with-audio --no-tts "音声なしで実行"
uv run ai-assistant-with-audio --verbose "判定スコアを表示"
```

| オプション | 内容 |
|---|---|
| `--new` / `--session ID` | セッションの自動判定を上書き |
| `--no-tts` | 音声生成・再生を行わない |
| `--voice-id` | Gemini の音声 ID を指定 |
| `--data-dir` | データ保存先（既定 `data`） |
| `--instructions` | LLM への指示ファイル（既定 `instructions.md`） |
| `--verbose` | セッション判定スコアと選択されたセッション ID を表示 |

## データ構造

```text
data/                       # gitignore 対象
  memory-bank.md            # 見出し（##）＋段落の単一 md
  sessions/
    <id>.summary.md         # 要約（frontmatter: id, title, created, updated）
    <id>.log.jsonl          # 会話ログ（1 行 1 ターン）
  archive/                  # 11 件目作成時に最古のセッションを要約のみ退避
instructions.md             # LLM へのシステム指示（編集可）
```

- セッションは最大 10 件です。11 件目を作る際に最終更新が最古のものを `archive/` へ移します。
- セッション判定は、要約に対する BM25（文字 bigram）の正規化スコアで行い、閾値以上なら最高スコアのセッションを継続します。
- memory-bank は `memory_updates`（`add` / `replace` / `delete`）で更新します。`replace` は `section` の本文全体を、`delete` は `text` を含む段落（`text` が空なら見出しごと）を対象とします。
- 個人情報が平文で保存されます。`data/` と `.env` は共有しないでください。

## 開発

```powershell
uv run pytest
```

テストは LLM・TTS をモックしています。
