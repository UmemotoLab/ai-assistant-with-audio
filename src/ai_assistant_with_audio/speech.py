import sys
import threading

from openrouter_audio.gemini import synthesize_with_voice_id


def _play_wav(wav: bytes) -> None:
    if sys.platform != "win32":
        print("音声の再生は Windows のみ対応しています", file=sys.stderr)
        return
    import winsound

    winsound.PlaySound(wav, winsound.SND_MEMORY)


def start_speech(
    api_key: str,
    voice_id: str,
    text: str,
    style: str | None = None,
) -> threading.Thread:
    """Synthesize and play `text` on a background thread. Errors are reported, not raised."""

    def run() -> None:
        try:
            result = synthesize_with_voice_id(api_key, text, voice_id, style=style)
            _play_wav(result.audio)
        except Exception as error:  # noqa: BLE001 - TTS must not break the text flow
            print(f"警告: 音声の生成・再生に失敗しました: {error}", file=sys.stderr)

    thread = threading.Thread(target=run, name="tts-playback")
    thread.start()
    return thread
