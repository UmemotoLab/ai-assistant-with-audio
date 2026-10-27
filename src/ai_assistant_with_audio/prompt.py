from collections.abc import Sequence

from ai_assistant_with_audio.sessions import Session, Turn

OUTPUT_CONTRACT = """\
あなたの応答は次のキーを持つ JSON オブジェクトのみとし、JSON 以外の文字を含めないでください。
- reply: ユーザに表示・読み上げるテキスト（必須）
- speech_style: 読み上げの口調指示。不要なら null
- session: セッションの作成・更新。更新不要なら null
  - title: 新規セッションのみ、短い題名。継続なら null
  - summary: 新規は要約全文、継続は更新後の要約全文。更新不要なら null
- memory_updates: memory-bank への変更の配列。不要なら空配列
  - op: add（section に text を段落として追記）/ replace（section の本文を text で置換）/ delete（text が空なら section を削除、text を含む段落を削除）
  - section: 見出し名（既存の見出しに合わせる。無ければ新規作成）
  - text: 内容

memory-bank には個人情報・好み・セッションをまたいで覚えるべき事実のみを記録してください。一時的な話題は記録しないでください。"""


def build_messages(
    instructions: str,
    memory_excerpt: str,
    user_message: str,
    session: Session | None = None,
    recent_turns: Sequence[Turn] = (),
) -> list[dict[str, str]]:
    memory_part = memory_excerpt.strip() or "（該当なし）"
    if session is None:
        user_content = (
            "## セッション\n新規\n\n"
            f"## memory-bank 抽出\n{memory_part}\n\n"
            f"## ユーザメッセージ\n{user_message}"
        )
    else:
        turns = "\n\n".join(
            f"[{turn.timestamp}]\nユーザ: {turn.user}\nアシスタント: {turn.assistant}"
            for turn in recent_turns
        ) or "（なし）"
        user_content = (
            f"## セッション\n継続（ID: {session.id}、題名: {session.title}）\n\n"
            f"## memory-bank 抽出\n{memory_part}\n\n"
            f"## セッション要約\n{session.summary}\n\n"
            f"## 直近の会話\n{turns}\n\n"
            f"## ユーザメッセージ\n{user_message}"
        )

    return [
        {"role": "system", "content": f"{instructions.strip()}\n\n{OUTPUT_CONTRACT}"},
        {"role": "user", "content": user_content},
    ]
