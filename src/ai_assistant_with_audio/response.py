import json
from dataclasses import dataclass, field
from typing import Any

MEMORY_OPS = ("add", "replace", "delete")

RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "speech_style", "session", "memory_updates"],
    "properties": {
        "reply": {"type": "string"},
        "speech_style": {"type": ["string", "null"]},
        "session": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["title", "summary"],
            "properties": {
                "title": {"type": ["string", "null"]},
                "summary": {"type": ["string", "null"]},
            },
        },
        "memory_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "section", "text"],
                "properties": {
                    "op": {"type": "string", "enum": list(MEMORY_OPS)},
                    "section": {"type": "string"},
                    "text": {"type": "string"},
                },
            },
        },
    },
}


class ResponseError(ValueError):
    """The LLM output does not satisfy the response contract."""


@dataclass(frozen=True)
class SessionUpdate:
    title: str | None
    summary: str | None


@dataclass(frozen=True)
class MemoryUpdate:
    op: str
    section: str
    text: str


@dataclass(frozen=True)
class ChatResponse:
    reply: str
    speech_style: str | None = None
    session: SessionUpdate | None = None
    memory_updates: list[MemoryUpdate] = field(default_factory=list)
    parsed: bool = True


def _optional_str(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ResponseError(f"{name} は文字列か null で指定してください")
    return value


def parse_response(raw: str) -> ChatResponse:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ResponseError(f"JSON として解析できません: {error}") from error
    if not isinstance(data, dict):
        raise ResponseError("トップレベルは JSON オブジェクトである必要があります")

    reply = data.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        raise ResponseError("reply は空でない文字列である必要があります")

    session_data = data.get("session")
    session = None
    if session_data is not None:
        if not isinstance(session_data, dict):
            raise ResponseError("session はオブジェクトか null である必要があります")
        session = SessionUpdate(
            title=_optional_str(session_data.get("title"), "session.title"),
            summary=_optional_str(session_data.get("summary"), "session.summary"),
        )

    updates_data = data.get("memory_updates") or []
    if not isinstance(updates_data, list):
        raise ResponseError("memory_updates は配列である必要があります")
    updates: list[MemoryUpdate] = []
    for item in updates_data:
        if not isinstance(item, dict):
            raise ResponseError("memory_updates の要素はオブジェクトである必要があります")
        op = item.get("op")
        section = item.get("section")
        text = item.get("text", "")
        if op not in MEMORY_OPS:
            raise ResponseError(f"memory_updates.op が不正です: {op!r}")
        if not isinstance(section, str) or not section.strip():
            raise ResponseError("memory_updates.section は空でない文字列である必要があります")
        if not isinstance(text, str):
            raise ResponseError("memory_updates.text は文字列である必要があります")
        updates.append(MemoryUpdate(op=op, section=section.strip(), text=text))

    return ChatResponse(
        reply=reply.strip(),
        speech_style=_optional_str(data.get("speech_style"), "speech_style"),
        session=session,
        memory_updates=updates,
    )


def fallback_response(raw: str) -> ChatResponse:
    """Use raw text as the reply; no session or memory updates are applied."""
    return ChatResponse(reply=raw.strip(), parsed=False)
