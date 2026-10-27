## Memo

* LLMはOpenRouter（`OPENROUTER_CHAT_MODEL`）。Web検索プラグイン（`plugins: [{"id": "web"}]`）を有効にしている
* 応答は JSON schema（strict）で受け取る
* memory-bankは単一md（`data/memory-bank.md`）に、個人情報・好み・その他セッションによらず記憶すべきことを記載
* セッションの保存先はローカルファイルフォルダ（`data/sessions/`）。最大10セッション。超えたら最古を `data/archive/` へ要約のみ退避
* セッション判定・memory抽出はどちらも BM25（日本語は文字 bigram）
* 直近会話は、セッションの新規・継続を問わず、全セッションのログから直近2ターンを渡す
* TTSは Gemini（`GEMINI_API_KEY`・`GEMINI_VOICE_ID`・`GEMINI_TTS_MODEL`）。`--no-tts` または未設定ならテキストのみ

## Flow

### 全体の流れ
```mermaid
flowchart TD
    A[CLI: mio メッセージ]
    A --> B{セッション指定}
    B -- "--new" --> N[新規]
    B -- "--session ID" --> S[指定セッションを継続]
    B -- 指定なし --> C[要約を BM25 検索
    正規化スコア最大のセッション]
    C --> D{スコア ≥ 閾値？
    既定 0.5}
    D -- Yes --> S
    D -- No --> N

    N --> M[memory-bank を BM25 検索
    上位5件の段落を抽出]
    S --> M
    M --> P[プロンプト組み立て]
    P --> L[LLM呼び出し・JSON応答]
```

### ユーザ入力を受けたときの最初 (セッションは自動判断)
```mermaid
flowchart TD
    A[ユーザメッセージ]
    A --> B{新規 / セッション選択}
    B -- 新規 --> X[memory-bank抽出
    LLMメッセージに追加]
    X --> C[新規セッションの流れ へ]
    B -- 継続 --> D[セッション要約をメッセージに追加]
    D --> X
    X --> E[継続セッションの流れ へ]
```

### 新規セッションの流れ
```mermaid
flowchart TD
    A[system: Instructions全文＋出力仕様
    user: セッション=新規
    ＋memory-bank抽出文
    ＋直近2ターン（全セッション）
    ＋ユーザメッセージ]
    A --> C[LLM呼び出し・JSON応答]
    C --> V{JSON検証OK？}
    V -- No --> R[エラー内容を添えて1回再試行]
    R --> V2{検証OK？}
    V2 -- No --> FB[応答を生テキストとして扱う
    セッション・memory-bankは更新しない]
    V -- Yes --> OK[応答を採用]
    V2 -- Yes --> OK
    FB --> D
    OK --> D[応答テキストを表示]
    OK --> E[TTS音声生成・再生]
    OK --> F[JSON解析]

    F --> G[新規セッションの作成
    題名は session.title、無ければメッセージ先頭30文字
    要約は session.summary、無ければユーザメッセージ]
    F --> H[memory-bankの更新判断]

    G --> K[10件を超える場合は最古をアーカイブ
    要約ファイル作成・会話ログ追記]
    H --> J{memory_updates あり？}
    J -- Yes --> L[memory-bank更新]
    J -- No --> O
    K --> O[処理終了
    TTS再生の完了を待つ]
    L --> O
```

### 継続セッションの流れ
```mermaid
flowchart TD
    A[system: Instructions全文＋出力仕様
    user: セッション=継続（ID・題名）
    ＋memory-bank抽出文
    ＋セッション要約全文
    ＋直近2ターン（全セッション）
    ＋ユーザメッセージ]
    A --> C[LLM呼び出し・JSON応答
    検証失敗時の再試行・フォールバックは新規と同じ]
    C --> D[応答テキストを表示]
    C --> E[TTS音声生成・再生]
    C --> F[JSON解析]

    F --> G[セッション要約の更新判断]
    F --> H[memory-bankの更新判断]

    G --> I{session.summary あり？}
    H --> J{memory_updates あり？}

    I -- Yes --> K[要約ファイル更新]
    J -- Yes --> L[memory-bank更新]
    I -- No --> M[会話ログ追記]
    J -- No --> M
    K --> M

    L --> M
    M --> O[処理終了
    TTS再生の完了を待つ]
```

### TTS（応答表示と並列）
```mermaid
flowchart TD
    A[応答テキスト] --> B[文単位で分割
    最初のチャンクは40文字以内
    以降は120文字以内]
    B --> C[最大3並列でGemini TTS合成]
    C --> D[チャンクを順番にwinsoundで再生]
    D --> E{失敗？}
    E -- Yes --> F[警告を表示して継続]
```

### JSON応答の仕様
```json
{
  "reply": "表示・読み上げるテキスト",
  "session": {"title": "新規時のみ", "summary": "要約全文 / 更新不要なら null"},
  "memory_updates": [{"op": "add|replace|delete", "section": "見出し", "text": "内容"}]
}
```
