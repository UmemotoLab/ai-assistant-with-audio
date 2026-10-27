import json
import shutil
from pathlib import Path

import pytest

from ai_assistant_with_audio import cli, llm, speech
from ai_assistant_with_audio.sessions import SessionStore

REPO_ROOT = Path(__file__).resolve().parents[1]


class _Done:
    def join(self):
        return None


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_CHAT_MODEL", "test/model")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_VOICE_ID", raising=False)
    monkeypatch.setattr("ai_assistant_with_audio.config.load_dotenv", lambda: None)
    instructions = tmp_path / "instructions.md"
    shutil.copy(REPO_ROOT / "instructions.md", instructions)
    spoken: list[str] = []

    def fake_start(api_key, voice_id, text, style=None):
        spoken.append(text)
        return _Done()

    monkeypatch.setattr(speech, "start_speech", fake_start)
    return {"data": tmp_path / "data", "instructions": instructions, "spoken": spoken}


def _responses(monkeypatch, *payloads):
    calls: list[list[dict]] = []
    queue = list(payloads)

    def fake_chat(api_key, model, messages, client=None):
        calls.append(messages)
        return queue.pop(0)

    monkeypatch.setattr(llm, "chat", fake_chat)
    return calls


def _base_args(env, message, *extra):
    return [message, "--data-dir", str(env["data"]), "--instructions", str(env["instructions"]), "--no-tts", *extra]


def test_new_session_is_created_and_memory_updated(env, monkeypatch, capsys):
    payload = json.dumps(
        {
            "reply": "わかりました",
            "speech_style": None,
            "session": {"title": "テスト", "summary": "テスト発話をした"},
            "memory_updates": [{"op": "add", "section": "好み", "text": "テスト好き"}],
        },
        ensure_ascii=False,
    )
    _responses(monkeypatch, payload)

    assert cli.main(_base_args(env, "テスト発話")) == 0

    assert "わかりました" in capsys.readouterr().out
    sessions = SessionStore(env["data"]).load_all()
    assert len(sessions) == 1 and sessions[0].title == "テスト"
    assert "テスト好き" in (env["data"] / "memory-bank.md").read_text(encoding="utf-8")


def test_continuing_session_appends_log_and_sends_context(env, monkeypatch):
    first = json.dumps({"reply": "一回目", "session": {"title": "会話", "summary": "最初の話題"}, "memory_updates": []})
    second = json.dumps({"reply": "二回目", "session": None, "memory_updates": []})
    calls = _responses(monkeypatch, first, second)

    assert cli.main(_base_args(env, "最初の話題について")) == 0
    session_id = SessionStore(env["data"]).load_all()[0].id
    assert cli.main(_base_args(env, "最初の話題の続き", "--session", session_id)) == 0

    continuing_user_content = calls[1][1]["content"]
    assert "最初の話題" in continuing_user_content
    log_lines = (env["data"] / "sessions" / f"{session_id}.log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 2


def test_automatic_selection_continues_matching_session(env, monkeypatch):
    first = json.dumps({"reply": "一回目", "session": {"title": "京都", "summary": "京都旅行の日程を相談"}, "memory_updates": []})
    second = json.dumps({"reply": "二回目", "session": None, "memory_updates": []})
    _responses(monkeypatch, first, second)

    assert cli.main(_base_args(env, "京都旅行の日程")) == 0
    assert cli.main(_base_args(env, "京都旅行の予算", "--verbose")) == 0

    assert len(SessionStore(env["data"]).load_all()) == 1


def test_invalid_json_retries_then_falls_back_without_updates(env, monkeypatch, capsys):
    calls = _responses(monkeypatch, "プレーンテキスト", "まだ不正")

    assert cli.main(_base_args(env, "テスト")) == 0

    assert len(calls) == 2
    assert "まだ不正" in capsys.readouterr().out
    assert SessionStore(env["data"]).load_all() == []


def test_tts_is_started_when_configured(env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    monkeypatch.setenv("GEMINI_VOICE_ID", "voice_1")
    payload = json.dumps({"reply": "読み上げ", "session": None, "memory_updates": []})
    _responses(monkeypatch, payload)

    args = [a for a in _base_args(env, "テスト") if a != "--no-tts"]
    assert cli.main(args) == 0
    assert env["spoken"] == ["読み上げ"]


def test_missing_api_key_reports_error(env, monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert cli.main(_base_args(env, "テスト")) == 1
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err
