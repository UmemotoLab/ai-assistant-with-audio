# 実装計画

flow.md の仕様をもとにした実装計画です。

## 決定事項

| 項目 | 内容 |
|---|---|
| UI | CLI を1回実行し、引数でメッセージを渡す。音声入力（STT）は無し |
| 対話LLM | OpenRouter。`OPENROUTER_API_KEY` と新設の `OPENROUTER_CHAT_MODEL` を使う |
| TTS | `GEMINI_API_KEY` で既存の `openrouter_audio/gemini.py` の `synthesize_with_voice_id` を再利用する。再生は応答表示と並列 |
| セッション判定 | BM25。閾値未満なら新規、以上なら最高スコアのセッションを継続 |
| memory 抽出 | BM25 で検索し、見出し／段落単位で抽出する |
| 日本語トークナイズ | 文字 bigram（依存なし） |
| セッション数 | 最大10。超えたら最古を要約アーカイブする |
| 直近会話 | 直近3ターン |
| 保存先 | `./data/`（gitignore） |
| Instructions | `instructions.md`（編集可） |
| 実装場所 | `ai_assistant_with_audio` パッケージに新規実装し、`openrouter_audio` は依存として再利用 |

## ディレクトリ構成

```text
data/                       # gitignore
  memory-bank.md            # 見出し＋段落形式の単一md
  sessions/
    <id>.summary.md         # 要約（frontmatter: id, created, updated, title）
    <id>.log.jsonl          # 全会話ログ（1行1ターン）
  archive/                  # 最古を要約アーカイブしたもの（要約のみ）
instructions.md             # LLMへのシステム指示（リポジトリ直下）
src/ai_assistant_with_audio/
  cli.py        # 引数・全体フロー
  config.py     # .env / パス / 閾値
  bm25.py       # bigramトークナイザ + BM25（自前実装）
  memory.py     # memory-bank 読込・段落分割・検索・更新
  sessions.py   # 保存・読込・選択・10件管理・アーカイブ
  prompt.py     # メッセージ組み立て（新規 / 継続）
  llm.py        # OpenRouter chat（JSON応答）
  response.py   # JSON スキーマ検証・解析
  speech.py     # TTS生成＋非ブロッキング再生
```

## LLM JSON 応答スキーマ（案）

```json
{
  "reply": "表示・読み上げるテキスト",
  "session": {
    "title": "新規時のみ",
    "summary": "新規は要約全文 / 継続は更新後の要約全文。更新不要なら null"
  },
  "memory_updates": [
    {"op": "add|replace|delete", "section": "見出し", "text": "内容"}
  ]
}
```

- `session.summary` が null ならセッションの作成・更新をしない。
- `memory_updates` が空配列なら memory-bank を更新しない。
- `response_format` に JSON schema を指定する。不正時は1回リトライし、それでも失敗したら `reply` を生テキストとして扱い、更新はスキップする。

## 処理フロー

1. ユーザメッセージを受け取る。
2. BM25 でセッション要約を検索する。最高スコアが閾値以上なら継続、未満なら新規。
3. memory-bank を BM25 で検索し、抽出文を得る。
4. 新規: Instructions＋memory抽出＋ユーザメッセージ。継続: Instructions＋memory抽出＋要約全文＋直近2ターン（全セッション）＋ユーザメッセージ。
5. OpenRouter を JSON 応答で呼び出す。
6. 応答を表示し、同時に TTS 生成・再生を別スレッドで行う。
7. JSON を解析し、セッション要約と memory-bank を更新する。会話ログを追記する。
8. 11件目のセッションを作成する場合は、最終更新が最古のセッションを `archive/` へ移す。

## 実装ステップ

1. **基盤**
   - `pyproject.toml` の依存に `httpx`、`python-dotenv`、再生用ライブラリを追加する（現状は空）。
   - `uv_build` で `openrouter_audio` もパッケージに含める設定にする。
   - `.gitignore` に `data/` と `.env` を追加する。
   - `config.py` で環境変数を読む（`OPENROUTER_API_KEY`、`OPENROUTER_CHAT_MODEL`、`GEMINI_API_KEY`、`GEMINI_VOICE_ID`）。
2. **BM25 とトークナイザ**
   - 文字 bigram（英数字は単語単位）でトークナイズする。
   - BM25 を自前実装する。
   - 単体テストを書く。
3. **memory-bank**
   - md を見出し／段落単位に分割する。
   - ユーザメッセージで BM25 検索し、上位K件を抽出文として返す。
   - `memory_updates` を適用する（add / replace / delete）。
   - 書き込みは一時ファイル＋置換でアトミックにする。
4. **セッション管理**
   - 要約と会話ログを保存・読込する。
   - 要約を BM25 コーパスにして継続／新規を判定する。
   - 直近2ターンを全セッションのログから取得する（セッションの継続・新規を問わない）。
   - 10件超過時は最古を `archive/` へ移す。
5. **プロンプト組み立て**（新規／継続の2種）
6. **LLM 呼び出しとレスポンス処理**
   - OpenRouter chat completions を JSON 応答で呼び出し、検証する。
   - 新規ならセッションを作成し、継続なら要約を更新する。どちらも会話ログを追記する。
7. **TTS と表示**
   - 応答表示と並列に TTS 生成・再生する。
   - 口調は Gemini の voice ID で調整する（`speech_style` は使わない）。
   - TTS が失敗してもテキスト応答と保存処理は継続する。
   - `--no-tts` を追加する。
   - 終了時は再生の完了を待つ。
8. **CLI**
   - `ai-assistant-with-audio "メッセージ"` で実行する。
   - オプション: `--new`（強制新規）、`--session ID`（強制継続）、`--no-tts`、`--voice-id`、`--data-dir`、`--verbose`（判定スコア表示）。
   - `pyproject.toml` の `[project.scripts]` を `cli:main` に向ける。
9. **テスト・ドキュメント**
   - LLM・TTS・HTTP をモックして次を pytest で確認する。
     - 新規・継続の分岐
     - 10件超過時のアーカイブ
     - JSON 不正時のフォールバック
   - `README.md` にセットアップ、`.env`、使い方、データ構造を書く。
   - `instructions.md` の初版と `data/memory-bank.md` の雛形を用意する。

## リスクと注意点

- **TTS の voice 指定**: 既存の Gemini 呼び出しは `voice_...` 形式の永続 ID が前提。プリセット名（Kore 等）が通るかは未確認のため、実機で確認する。通らなければ `GEMINI_VOICE_ID` を必須にする。
- **再生方式**: 24kHz/16bit/mono の WAV が返るため、標準の `winsound`（Windows 専用）か `sounddevice` を候補とする。
- **BM25 の限界**: 「それ」「さっきの」などの短い継続発話は閾値に届かず新規扱いになりうる。閾値調整、または最終セッションからの経過時間を補助条件にすることを検討する。
- **プライバシー**: 個人情報が平文で保存される。`data/` は gitignore に入れる。

## 未決事項

1. `GEMINI_VOICE_ID` を `.env` で持つ方針でよいか。
2. 再生ライブラリは `winsound`（Windows 専用）でよいか。
3. 実装に進んでよいか。
