import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

import httpx

from ai_assistant_with_audio import llm, speech
from ai_assistant_with_audio.config import (
    DEFAULT_DATA_DIR,
    DEFAULT_INSTRUCTIONS_FILE,
    Config,
    load_config,
)
from ai_assistant_with_audio.memory import TEMPLATE, MemoryBank
from ai_assistant_with_audio.prompt import build_messages
from ai_assistant_with_audio.response import (
    ChatResponse,
    ResponseError,
    fallback_response,
    parse_response,
)
from ai_assistant_with_audio.sessions import Session, SessionStore

TITLE_MAX_LENGTH = 30


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-assistant-with-audio",
        description="OpenRouter のチャットモデルで応答し、Gemini TTS で読み上げます。",
    )
    parser.add_argument("message", help="ユーザメッセージ")

    session_mode = parser.add_mutually_exclusive_group()
    session_mode.add_argument("--new", action="store_true", help="セッションを自動判定せず新規で開始する")
    session_mode.add_argument("--session", metavar="ID", help="指定したセッションを継続する")

    parser.add_argument("--no-tts", action="store_true", help="音声生成・再生を行わない")
    parser.add_argument("--voice-id", help="Gemini の voice ID（.env の GEMINI_VOICE_ID より優先）")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="データ保存先（既定: data）")
    parser.add_argument(
        "--instructions",
        type=Path,
        default=DEFAULT_INSTRUCTIONS_FILE,
        help="LLM への指示ファイル（既定: instructions.md）",
    )
    parser.add_argument("--verbose", action="store_true", help="セッション判定スコアなどを表示する")
    return parser


def _parse_with_retry(config: Config, messages: list[dict[str, str]], raw: str) -> ChatResponse:
    try:
        return parse_response(raw)
    except ResponseError as error:
        retry_messages = [
            *messages,
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": f"前回の応答が仕様に合いませんでした（{error}）。仕様どおりの JSON オブジェクトのみを再出力してください。",
            },
        ]
        retried = llm.chat(config.openrouter_api_key, config.chat_model, retry_messages)
        try:
            return parse_response(retried)
        except ResponseError:
            return fallback_response(retried)


def _save(
    store: SessionStore,
    memory: MemoryBank,
    session: Session | None,
    message: str,
    response: ChatResponse,
    now: datetime,
) -> Session | None:
    if not response.parsed:
        print("警告: 応答の JSON 解析に失敗したため、セッションと memory-bank は更新しません", file=sys.stderr)
        return session

    summary = response.session.summary if response.session else None
    if session is None:
        title = (response.session.title if response.session else None) or message[:TITLE_MAX_LENGTH]
        session = store.create(title, summary or message, now)
    elif summary:
        session = store.update_summary(session, summary, now)
    memory.apply_updates(response.memory_updates)
    return session


def run(args: argparse.Namespace) -> int:
    message = args.message.strip()
    if not message:
        raise ValueError("メッセージが空です")

    config = load_config()
    instructions = args.instructions.read_text(encoding="utf-8")

    store = SessionStore(args.data_dir)
    store.ensure_dirs()
    memory = MemoryBank(args.data_dir / "memory-bank.md")
    if not memory.path.exists():
        memory.path.write_text(TEMPLATE, encoding="utf-8")

    session: Session | None = None
    score = 0.0
    if args.session:
        session = store.get(args.session)
        if session is None:
            raise ValueError(f"セッションが見つかりません: {args.session}")
    elif not args.new:
        session, score = store.select(message, config.session_threshold)
    if args.verbose:
        label = session.id if session else "新規"
        print(
            f"[verbose] score={score:.2f} threshold={config.session_threshold} session={label}",
            file=sys.stderr,
        )

    messages = build_messages(
        instructions,
        memory.search(message),
        message,
        session,
        store.recent_turns(),
    )
    response = _parse_with_retry(
        config,
        messages,
        llm.chat(config.openrouter_api_key, config.chat_model, messages),
    )

    speech_thread = None
    voice_id = args.voice_id or config.gemini_voice_id
    if not args.no_tts:
        if config.gemini_api_key and voice_id:
            speech_thread = speech.start_speech(config.gemini_api_key, voice_id, response.reply)
        else:
            print("警告: 音声は無効です（GEMINI_API_KEY と GEMINI_VOICE_ID の設定が必要）", file=sys.stderr)

    print(response.reply)

    now = datetime.now().astimezone()
    session = _save(store, memory, session, message, response, now)
    if session is not None:
        store.append_turn(session.id, message, response.reply, now)
    if args.verbose and session is not None:
        print(f"[verbose] session={session.id}", file=sys.stderr)

    if speech_thread is not None:
        speech_thread.join()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (ValueError, RuntimeError, OSError, httpx.HTTPError) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1
