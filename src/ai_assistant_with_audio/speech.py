import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from openrouter_audio.gemini import synthesize_with_voice_id

FIRST_CHUNK_MAX_CHARS = 40
CHUNK_MAX_CHARS = 120
MAX_WORKERS = 3

_SENTENCE_PATTERN = re.compile(r".+?(?:[。！？!?]+|\n+|$)", re.DOTALL)
_MARKDOWN_LINK_PATTERN = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<url>[^)]+)\)")


def clean_for_speech(text: str) -> str:
    """Convert Markdown links and raw URLs into TTS-friendly text.

    Examples:
        [openrouter.ai](https://openrouter.ai/typesafe) -> openrouter.aiのリンクを見てね
        https://example.com/foo -> example.comのリンクを見てね
    """
    text = _MARKDOWN_LINK_PATTERN.sub(r"\g<label>のリンクを見てね", text)
    text = re.sub(
        r"https?://(?P<host>[^/]+)(?:/[^\s]*)?",
        r"\g<host>のリンクを見てね",
        text,
    )
    return text


def split_text(text: str) -> list[str]:
    """Split text into sentence-based chunks; the first is short so playback starts early."""
    text = clean_for_speech(text)
    sentences = [s.strip() for s in _SENTENCE_PATTERN.findall(text) if s.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        limit = FIRST_CHUNK_MAX_CHARS if not chunks else CHUNK_MAX_CHARS
        if current and len(current) + len(sentence) > limit:
            chunks.append(current)
            current = ""
        current += sentence
    if current:
        chunks.append(current)
    return chunks


def _play_wav(wav: bytes) -> None:
    if sys.platform != "win32":
        print("音声の再生は Windows のみ対応しています", file=sys.stderr)
        return
    import winsound

    winsound.PlaySound(wav, winsound.SND_MEMORY)


def start_speech(api_key: str, voice_id: str, text: str) -> threading.Thread:
    """Synthesize chunks in parallel and play them in order on a background thread.

    Errors are reported, not raised.
    """

    def synthesize(chunk: str) -> bytes:
        return synthesize_with_voice_id(api_key, chunk, voice_id).audio

    def run() -> None:
        chunks = split_text(text) or [text]
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [pool.submit(synthesize, chunk) for chunk in chunks]
            for future in futures:
                try:
                    _play_wav(future.result())
                except Exception as error:  # noqa: BLE001 - TTS must not break the text flow
                    print(f"警告: 音声の生成・再生に失敗しました: {error}", file=sys.stderr)

    thread = threading.Thread(target=run, name="tts-playback")
    thread.start()
    return thread
