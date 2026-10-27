from typing import Any, Sequence

import httpx

from ai_assistant_with_audio.response import RESPONSE_JSON_SCHEMA
from openrouter_audio.client import TIMEOUT_SECONDS, error_message

API_URL = "https://openrouter.ai/api/v1/chat/completions"


def chat(
    api_key: str,
    model: str,
    messages: Sequence[dict[str, str]],
    client: httpx.Client | None = None,
) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "messages": list(messages),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "assistant_response",
                "strict": True,
                "schema": RESPONSE_JSON_SCHEMA,
            },
        },
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    if client is None:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as owned_client:
            response = owned_client.post(API_URL, json=payload, headers=headers)
    else:
        response = client.post(API_URL, json=payload, headers=headers, timeout=TIMEOUT_SECONDS)

    if not response.is_success:
        raise RuntimeError(error_message(response))

    body = response.json()
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("API の応答に本文が含まれていません") from error
    if not isinstance(content, str):
        raise RuntimeError("API の応答本文が文字列ではありません")
    return content
