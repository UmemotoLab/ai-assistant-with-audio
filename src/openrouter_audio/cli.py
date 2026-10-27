import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import httpx

from openrouter_audio.client import (
    DEFAULT_VOICE,
    VOICES,
    SpeechRequest,
    pcm_to_wav,
    save_audio,
    synthesize,
)
from openrouter_audio.gemini import synthesize_with_voice_id
from openrouter_audio.settings import load_gemini_api_key, load_settings

MAX_ID_LENGTH = 256
DEFAULT_OUTPUT_DIR = Path("outputs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openrouter-audio",
        description="OpenRouter の google/gemini-3.8-flash-tts で音声を生成して保存します。",
    )

    text_source = parser.add_mutually_exclusive_group(required=True)
    text_source.add_argument("--text", help="読み上げる本文")
    text_source.add_argument("--input-file", type=Path, help="読み上げる本文を含む UTF-8 のファイル")

    voice_source = parser.add_mutually_exclusive_group()
    voice_source.add_argument("--voice", choices=VOICES, help=f"音声の種類（既定: {DEFAULT_VOICE}。API は voice の指定を必須とする）")
    voice_source.add_argument(
        "--voice-id",
        help="Gemini API の永続的な voice ID（voice_...）。OpenRouter ではなく Gemini API を直接呼び出す（.env の GEMINI_API_KEY が必要）",
    )
    parser.add_argument("--format", dest="response_format", choices=["pcm"], default="pcm", help="API への出力形式（Gemini TTS は pcm のみ対応）")
    parser.add_argument("--instructions", help="口調・速度感・感情などの指示")
    parser.add_argument("--speed", type=float, help="再生速度（Gemini TTS で非対応の場合は API がエラーを返します）")
    parser.add_argument("--data-collection", choices=["allow", "deny"], help="provider.data_collection")
    parser.add_argument("--zdr", action="store_true", help="ゼロデータ保持のプロバイダーのみを使用")
    parser.add_argument("--provider-options", metavar="JSON", help="provider.options に渡す JSON オブジェクト")
    parser.add_argument("--session-id", help=f"ログ用のセッション ID（最大 {MAX_ID_LENGTH} 文字）")
    parser.add_argument("--user", help=f"エンドユーザー ID（最大 {MAX_ID_LENGTH} 文字）")

    parser.add_argument("--output", type=Path, help="保存先（省略時は outputs/<日時>.<拡張子>）")
    parser.add_argument("--overwrite", action="store_true", help="既存ファイルを上書きする")
    parser.add_argument("--raw-pcm", action="store_true", help="WAV 変換せず生の PCM のまま保存する")
    return parser


def _read_text(args: argparse.Namespace) -> str:
    if args.input_file is not None:
        text = args.input_file.read_text(encoding="utf-8")
    else:
        text = args.text
    if not text.strip():
        raise ValueError("読み上げる本文が空です")
    return text


def _parse_provider_options(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    options = json.loads(raw)
    if not isinstance(options, dict):
        raise ValueError("--provider-options は JSON オブジェクトで指定してください")
    return options


def _check_id(name: str, value: str | None) -> None:
    if value is not None and len(value) > MAX_ID_LENGTH:
        raise ValueError(f"{name} は {MAX_ID_LENGTH} 文字以内で指定してください")


def _default_output(extension: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return DEFAULT_OUTPUT_DIR / f"{stamp}.{extension}"


def _check_gemini_options(args: argparse.Namespace) -> None:
    unsupported = {
        "--speed": args.speed is not None,
        "--data-collection": args.data_collection is not None,
        "--zdr": args.zdr,
        "--provider-options": args.provider_options is not None,
        "--session-id": args.session_id is not None,
        "--user": args.user is not None,
        "--raw-pcm": args.raw_pcm,
    }
    used = [name for name, is_set in unsupported.items() if is_set]
    if used:
        raise ValueError(f"--voice-id（Gemini API 直接）では次のオプションは使えません: {', '.join(used)}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        return _run(args)
    except (ValueError, RuntimeError, OSError, httpx.HTTPError) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1


def _run_gemini(args: argparse.Namespace, text: str) -> int:
    _check_gemini_options(args)
    if args.output is not None and args.output.exists() and not args.overwrite:
        raise FileExistsError(f"既に存在します: {args.output} (上書きするには --overwrite を指定)")

    result = synthesize_with_voice_id(
        load_gemini_api_key(), text, args.voice_id, style=args.instructions
    )
    saved = save_audio(result, args.output or _default_output("wav"), overwrite=args.overwrite)
    print(f"保存しました: {saved}")
    return 0


def _run(args: argparse.Namespace) -> int:
    text = _read_text(args)
    if args.voice_id:
        return _run_gemini(args, text)

    _check_id("--session-id", args.session_id)
    _check_id("--user", args.user)
    provider_options = _parse_provider_options(args.provider_options)

    if args.output is not None and args.output.exists() and not args.overwrite:
        raise FileExistsError(f"既に存在します: {args.output} (上書きするには --overwrite を指定)")

    settings = load_settings()
    request = SpeechRequest(
        input=text,
        voice=args.voice or DEFAULT_VOICE,
        response_format=args.response_format,
        instructions=args.instructions,
        speed=args.speed,
        data_collection=args.data_collection,
        zdr=args.zdr or None,
        provider_options=provider_options,
        session_id=args.session_id,
        user=args.user,
    )

    result = synthesize(settings, request)

    if args.raw_pcm:
        extension = "pcm"
    else:
        result = replace(result, audio=pcm_to_wav(result.audio))
        extension = "wav"

    saved = save_audio(result, args.output or _default_output(extension), overwrite=args.overwrite)
    print(f"保存しました: {saved}")
    if result.generation_id:
        print(f"生成 ID: {result.generation_id}")
    return 0