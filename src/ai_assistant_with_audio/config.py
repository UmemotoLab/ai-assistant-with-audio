import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_DATA_DIR = Path("data")
DEFAULT_INSTRUCTIONS_FILE = Path("instructions.md")
DEFAULT_SESSION_THRESHOLD = 0.5
MAX_SESSIONS = 10
RECENT_TURNS = 3
MEMORY_TOP_K = 5


@dataclass(frozen=True)
class Config:
    openrouter_api_key: str = field(repr=False)
    chat_model: str
    gemini_api_key: str | None = field(default=None, repr=False)
    gemini_voice_id: str | None = None
    session_threshold: float = DEFAULT_SESSION_THRESHOLD


def load_config() -> Config:
    load_dotenv()

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    chat_model = os.environ.get("OPENROUTER_CHAT_MODEL", "").strip()
    missing = [
        name
        for name, value in (("OPENROUTER_API_KEY", api_key), ("OPENROUTER_CHAT_MODEL", chat_model))
        if not value
    ]
    if missing:
        raise ValueError(f"環境変数が未設定です: {', '.join(missing)} (.env を確認してください)")

    threshold_raw = os.environ.get("SESSION_MATCH_THRESHOLD", "").strip()
    threshold = float(threshold_raw) if threshold_raw else DEFAULT_SESSION_THRESHOLD

    return Config(
        openrouter_api_key=api_key,
        chat_model=chat_model,
        gemini_api_key=os.environ.get("GEMINI_API_KEY", "").strip() or None,
        gemini_voice_id=os.environ.get("GEMINI_VOICE_ID", "").strip() or None,
        session_threshold=threshold,
    )
