import io
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from openrouter_audio.settings import Settings

API_URL = "https://openrouter.ai/api/v1/audio/speech"
TIMEOUT_SECONDS = 120.0
# この TTS プロバイダーは voice の指定を必須とするため、CLI の既定値に使う
DEFAULT_VOICE = "Kore"

# Google の Gemini API ドキュメントの値。OpenRouter 経由での実音声確認は未実施。
PCM_SAMPLE_RATE = 24000
PCM_SAMPLE_WIDTH = 2  # bytes (16 bit)
PCM_CHANNELS = 1

VOICES: tuple[str, ...] = (
    "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede",
    "Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba",
    "Despina", "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar",
    "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
    "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
)


@dataclass(frozen=True)
class SpeechRequest:
    input: str
    voice: str | None = None
    response_format: str | None = None
    instructions: str | None = None
    speed: float | None = None
    data_collection: str | None = None
    zdr: bool | None = None
    provider_options: dict[str, Any] | None = None
    session_id: str | None = None
    user: str | None = None


@dataclass(frozen=True)
class SpeechResult:
    audio: bytes
    content_type: str
    generation_id: str | None


def build_payload(model: str, req: SpeechRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model, "input": req.input}

    optional = {
        "voice": req.voice,
        "response_format": req.response_format,
        "instructions": req.instructions,
        "speed": req.speed,
        "session_id": req.session_id,
        "user": req.user,
    }
    payload.update({key: value for key, value in optional.items() if value is not None})

    provider: dict[str, Any] = {}
    if req.data_collection is not None:
        provider["data_collection"] = req.data_collection
    if req.zdr:
        provider["zdr"] = True
    if req.provider_options is not None:
        provider["options"] = req.provider_options
    if provider:
        payload["provider"] = provider

    return payload


def synthesize(
    settings: Settings,
    req: SpeechRequest,
    client: httpx.Client | None = None,
) -> SpeechResult:
    payload = build_payload(settings.model, req)
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }

    if client is None:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as owned_client:
            response = owned_client.post(API_URL, json=payload, headers=headers)
    else:
        response = client.post(API_URL, json=payload, headers=headers, timeout=TIMEOUT_SECONDS)

    if not response.is_success:
        raise RuntimeError(error_message(response))

    return SpeechResult(
        audio=response.content,
        content_type=response.headers.get("Content-Type", ""),
        generation_id=response.headers.get("X-Generation-Id"),
    )


def error_message(response: httpx.Response) -> str:
    try:
        error = response.json().get("error", {})
        message = error.get("message") or str(error)
    except (ValueError, AttributeError):
        message = response.text or response.reason_phrase
    return f"API エラー (HTTP {response.status_code}): {message}"


def save_audio(result: SpeechResult, path: Path, overwrite: bool = False) -> Path:
    path = Path(path)
    if path.exists() and not overwrite:
        raise FileExistsError(f"既に存在します: {path} (上書きするには --overwrite を指定)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(result.audio)
    return path


def pcm_to_wav(
    pcm: bytes,
    sample_rate: int = PCM_SAMPLE_RATE,
    sample_width: int = PCM_SAMPLE_WIDTH,
    channels: int = PCM_CHANNELS,
) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()
