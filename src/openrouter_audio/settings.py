import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    model: str


def load_gemini_api_key() -> str:
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("環境変数が未設定です: GEMINI_API_KEY (.env を確認してください)")
    return api_key


def load_gemini_tts_model() -> str:
    load_dotenv()
    model = os.environ.get("GEMINI_TTS_MODEL", "").strip()
    if not model:
        raise ValueError("環境変数が未設定です: GEMINI_TTS_MODEL (.env を確認してください)")
    return model


def load_settings() -> Settings:
    load_dotenv()

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    model = os.environ.get("OPENROUTER_MODEL", "").strip()

    missing = [
        name
        for name, value in (("OPENROUTER_API_KEY", api_key), ("OPENROUTER_MODEL", model))
        if not value
    ]
    if missing:
        raise ValueError(f"環境変数が未設定です: {', '.join(missing)} (.env を確認してください)")

    return Settings(api_key=api_key, model=model)
