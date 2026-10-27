# 設計・実装状況

flow.md の仕様に基づく実装の設計です。**実装は完了しており**、以下は現在のコードの状態を反映しています。使い方は [README.md](README.md) を参照してください。

## 決定事項

| 項目 | 内容 |
|---|---|
| UI | CLI を1回実行し、引数でメッセージを渡す（`mio` / `ai-assistant-with-audio`）。音声入力（STT）は無し |
| 対話LLM | OpenRouter chat completions。`OPENROUTER_API_KEY` と `OPENROUTER_CHAT_MODEL`。Web プラグイン（`plugins: [{"id": "web"}]`）有効、`response_format` は JSON schema（strict） |
| TTS | Gemini Interactions API（`openrouter_audio/gemini.py` の `synthesize_with_voice_id`）。`GEMINI_API_KEY`・`GEMINI_VOICE_ID`・`GEMINI_TTS_MODEL` を使う。再生は `winsound`（Windows 専用） |
| セッション判定 | 要約（題名＋要約）を BM25 で検索し、正規化スコアが閾値（既定 0.5、`SESSION_MATCH_THRESHOLD`）以上なら最高スコアのセッションを継続、未満なら新規 |
| memory 抽出 | `##` 見出し＋段落を単位に BM25 検索し、スコア > 0 の上位5件を抽出する |
| 日本語トークナイズ | ASCII は単語単位、日本語は文字 bigram（依存なし） |
| セッション数 | 最大10。11件目を作る際に最終更新が最古のセッションを `archive/` へ要約のみ退避し、ログは削除する |
| 直近会話 | 全セッションのログから直近2ターン（新規・継続を問わず渡す） |
| 保存先 | `data/`（gitignore）。リポジトリルート基準で、実行フォルダに依存しない |
| Instructions | `instructions.md`（編集可）。コードの出力仕様（`OUTPUT_CONTRACT`）をシステムメッセージ末尾に付加する |
| パッケージ | `ai_assistant_with_audio` が本体。`openrouter_audio`（TTS クライアント等）も同じ wheel に含める |

## ディレクトリ構成

```text
data/                       # gitignore
  memory-bank.md            # 見出し（##）＋段落形式の単一md。無ければ雛形を作成
  sessions/
    <id>.summary.md         # 要約（frontmatter: id, title, created, updated）
    <id>.log.jsonl          # 会話ログ（1行1ターン: ts, user, assistant）
  archive/                  # 最古を要約のみアーカイブしたもの
instructions.md             # LLMへのシステム指示（リポジトリ直下）
.env / .env.example         # 環境変数
src/ai_assistant_with_audio/
  cli.py        # 引数・全体フロー・JSON検証の再試行・保存
  config.py     # .env / パス / 定数（MAX_SESSIONS=10, RECENT_TURNS=2, MEMORY_TOP_K=5）
  bm25.py       # トークナイザ + BM25（自前実装、正規化スコア）
  memory.py     # memory-bank 読込・段落分割・検索・更新（アトミック書き込み）
  sessions.py   # 保存・読込・選択・10件管理・アーカイブ・直近ターン取得
  prompt.py     # メッセージ組み立て（新規 / 継続）＋出力仕様
  llm.py        # OpenRouter chat（JSON schema 応答）
  response.py   # JSON schema・検証・フォールバック
  speech.py     # 文分割＋並列TTS合成＋順次再生（バックグラウンドスレッド）
src/openrouter_audio/       # TTS クライアント（Gemini / OpenRouter）と単体CLI
tests/
  test_core.py  # BM25・memory・sessions・llm・response
  test_cli.py   # 新規/継続・フォールバック・TTS起動・設定エラー
  test_speech.py
```

## LLM JSON 応答スキーマ

```json
{
  "reply": "表示・読み上げるテキスト",
  "session": {
    "title": "新規時のみ。継続は null",
    "summary": "新規は要約全文 / 継続は更新後の要約全文。更新不要なら null"
  },
  "memory_updates": [
    {"op": "add|replace|delete", "section": "見出し", "text": "内容"}
  ]
}
```

- `reply` は必須で空不可。`session` は null も可。
- 新規セッションでは、`session` が null でも（解析成功時は）セッションを作成する。題名は `session.title`、無ければメッセージ先頭30文字。要約は `session.summary`、無ければユーザメッセージ。
- 継続セッションでは `session.summary` が null／空なら要約を更新しない。
- `memory_updates` が空配列なら memory-bank を更新しない。
  - `add`: `section` に `text` を段落として追記（見出しが無ければ新規作成）
  - `replace`: `section` の本文全体を `text` で置換
  - `delete`: `text` が空なら見出しごと、あれば `text` を含む段落を削除
- 検証に失敗したら、エラー内容を添えて1回再試行する。それでも失敗した場合は応答を生テキストとして `reply` に使い、セッション・memory-bank は更新しない（会話ログも追記しない）。

## 処理フロー

1. CLI 引数を解析し、`.env` と `instructions.md` を読む。`data/` と `memory-bank.md` が無ければ作成する。
2. セッションを決める。`--session ID` は強制継続、`--new` は強制新規、どちらも無ければ BM25 で判定する（`--verbose` でスコア表示）。
3. memory-bank を BM25 で検索し、抽出文を得る。
4. メッセージを組み立てる。
   - system: Instructions＋出力仕様
   - user: セッション種別（新規／継続）、memory 抽出、（継続のみ）セッション要約全文、直近2ターン、ユーザメッセージ
5. OpenRouter を呼び出し、応答を検証する（失敗時は再試行、それでも失敗ならフォールバック）。
6. TTS が有効なら別スレッドで合成・再生を開始し、並行して `reply` を標準出力に表示する。
   - 文単位に分割（最初のチャンクは40文字以内で早く再生開始、以降は120文字以内）
   - 最大3並列で合成し、順番に再生する
   - 失敗しても警告のみで、テキスト応答と保存処理は継続する
7. セッションと memory-bank を更新し、会話ログを追記する。新規作成時は10件を超えないよう最古をアーカイブする。
8. TTS 再生の完了を待って終了する。

## 実装状況

| 項目 | 状況 |
|---|---|
| 基盤（依存・パッケージ設定・`.gitignore`・設定読込） | 完了（`httpx`・`python-dotenv`。再生は標準の `winsound`） |
| BM25・トークナイザ | 完了 |
| memory-bank（抽出・更新） | 完了 |
| セッション管理（保存・判定・アーカイブ・直近ターン） | 完了 |
| プロンプト組み立て・LLM呼び出し・応答検証 | 完了（再試行・フォールバックあり） |
| TTS（分割・並列合成・順次再生） | 完了 |
| CLI（`--new` `--session` `--no-tts` `--voice-id` `--data-dir` `--instructions` `--verbose`） | 完了 |
| テスト（LLM・TTS・HTTP はモック）・README・`instructions.md` | 完了 |

## 既知の制約・今後の検討

- **音声再生**: `winsound` のため Windows のみ。他 OS では警告を出して再生しない。
- **BM25 の限界**: 「それ」「さっきの」などの短い継続発話は、閾値に届かず新規扱いになりうる（正規化スコアは一致語が2語未満だと0）。閾値（`SESSION_MATCH_THRESHOLD`）の調整、または最終セッションからの経過時間を補助条件にすることを検討する。`--session` で強制継続もできる。
- **会話ログの欠落**: JSON 検証に失敗してフォールバックした場合、新規セッションが作られないため、そのターンはログに残らない（継続セッションでは追記される）。
- **プライバシー**: 個人情報が平文で保存される。`data/` と `.env` は gitignore 済みで、共有しない。
- **API 依存**: TTS は Gemini Interactions API、LLM の Web プラグインは OpenRouter の仕様に依存する。
