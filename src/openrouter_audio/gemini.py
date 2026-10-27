import base64
from typing import Any

import httpx

from openrouter_audio.client import TIMEOUT_SECONDS, SpeechResult, error_message

API_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
MODEL = "gemini-3.8-flash-tts"


def build_interaction_payload(text: str, voice_id: str, style: str | None = None) -> dict[str, Any]:
    part: dict[str, Any] = {"type": "text", "text": text}
    if style:
        part["annotations"] = [{"type": "speech_metadata", "style": style}]

    return {
        "model": MODEL,
        "input": [{"type": "user_input", "content": [part]}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice_id}]},
    }


def _extract_audio(body: dict[str, Any]) -> bytes:
    audio_parts = [
        part
        for step in body.get("steps", [])
        if step.get("type") == "model_output"
        for part in step.get("content", [])
        if part.get("type") == "audio" and part.get("data")
    ]
    if not audio_parts:
        raise RuntimeError("API の応答に音声データが含まれていません")
    return base64.b64decode(audio_parts[-1]["data"])


def synthesize_with_voice_id(
    api_key: str,
    text: str,
    voice_id: str,
    style: str | None = None,
    client: httpx.Client | None = None,
) -> SpeechResult:
    payload = build_interaction_payload(text, voice_id, style)
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    if client is None:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as owned_client:
            response = owned_client.post(API_URL, json=payload, headers=headers)
    else:
        response = client.post(API_URL, json=payload, headers=headers, timeout=TIMEOUT_SECONDS)

    if not response.is_success:
        raise RuntimeError(error_message(response))

    # 非ストリーミングの応答は RIFF ヘッダー付きの WAV (24 kHz / 16 bit / モノラル)
    return SpeechResult(audio=_extract_audio(response.json()), content_type="audio/wav", generation_id=None)
