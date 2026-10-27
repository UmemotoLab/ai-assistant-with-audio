import json
from datetime import datetime, timedelta

import pytest

from ai_assistant_with_audio.bm25 import BM25, tokenize
from ai_assistant_with_audio.config import DEFAULT_SESSION_THRESHOLD
from ai_assistant_with_audio.memory import MemoryBank
from ai_assistant_with_audio.response import (
    MemoryUpdate,
    ResponseError,
    fallback_response,
    parse_response,
)
from ai_assistant_with_audio.sessions import SessionStore


def test_tokenize_splits_japanese_into_bigrams_and_keeps_ascii_words():
    assert tokenize("東京タワー AI") == ["東京", "京タ", "タワ", "ワー", "ai"]


def test_bm25_ranks_matching_document_first():
    docs = ["旅行の計画について話した", "猫の餌を買った", "プログラミングの勉強"]
    scores = BM25(docs).scores("猫の餌")
    assert scores.index(max(scores)) == 1
    assert scores[0] < scores[1]


def test_memory_search_returns_relevant_paragraph(tmp_path):
    path = tmp_path / "memory-bank.md"
    path.write_text(
        "# Memory Bank\n\n## 個人情報\n\n名前は太郎です。\n\n## 好み\n\n辛い食べ物が好きです。\n",
        encoding="utf-8",
    )
    result = MemoryBank(path).search("辛い料理のおすすめ")
    assert "辛い食べ物が好きです" in result
    assert "名前は太郎" not in result


def test_memory_updates_add_replace_delete(tmp_path):
    path = tmp_path / "memory-bank.md"
    bank = MemoryBank(path)
    bank.apply_updates(
        [
            MemoryUpdate("add", "好み", "コーヒーが好き"),
            MemoryUpdate("add", "好み", "猫が好き"),
            MemoryUpdate("add", "個人情報", "誕生日は3月"),
        ]
    )
    text = path.read_text(encoding="utf-8")
    assert "## 好み" in text and "コーヒーが好き" in text and "猫が好き" in text

    bank.apply_updates([MemoryUpdate("delete", "好み", "コーヒー")])
    text = path.read_text(encoding="utf-8")
    assert "コーヒー" not in text and "猫が好き" in text

    bank.apply_updates([MemoryUpdate("replace", "個人情報", "誕生日は4月")])
    text = path.read_text(encoding="utf-8")
    assert "誕生日は4月" in text and "3月" not in text

    bank.apply_updates([MemoryUpdate("delete", "個人情報", "")])
    assert "## 個人情報" not in path.read_text(encoding="utf-8")


def test_session_create_select_and_update(tmp_path):
    store = SessionStore(tmp_path)
    now = datetime.now().astimezone()
    session = store.create("旅行計画", "京都旅行の日程を相談した", now)

    found, score = store.select("京都の旅行について", threshold=DEFAULT_SESSION_THRESHOLD)
    assert found is not None and found.id == session.id and score >= DEFAULT_SESSION_THRESHOLD

    unrelated, _ = store.select("量子コンピュータ", threshold=DEFAULT_SESSION_THRESHOLD)
    assert unrelated is None

    store.update_summary(session, "京都旅行の日程を決めた", now)
    assert store.get(session.id).summary == "京都旅行の日程を決めた"
    assert store.get(session.id).title == "旅行計画"


def test_recent_turns_span_sessions_and_keep_last_two(tmp_path):
    store = SessionStore(tmp_path)
    base = datetime(2026, 1, 1).astimezone()
    first = store.create("A", "要約A", base)
    second = store.create("B", "要約B", base)
    store.append_turn(first.id, "q1", "a1", base + timedelta(minutes=1))
    store.append_turn(second.id, "q2", "a2", base + timedelta(minutes=2))
    store.append_turn(first.id, "q3", "a3", base + timedelta(minutes=3))
    turns = store.recent_turns()
    assert [t.user for t in turns] == ["q2", "q3"]


def test_session_store_archives_oldest_beyond_ten(tmp_path):
    store = SessionStore(tmp_path)
    base = datetime(2026, 1, 1).astimezone()
    for index in range(10):
        store.create(f"s{index}", f"summary {index}", base + timedelta(hours=index))
    store.create("newest", "newest summary", base + timedelta(hours=20))

    remaining = store.load_all()
    assert len(remaining) == 10
    assert "s0" not in {s.title for s in remaining}
    assert len(list((tmp_path / "archive").glob("*.summary.md"))) == 1


def test_chat_requests_web_plugin():
    import httpx

    from ai_assistant_with_audio import llm

    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert llm.chat("key", "model", [{"role": "user", "content": "x"}], client=client) == "{}"
    assert sent["plugins"] == [{"id": "web"}]


def test_parse_valid_response():
    raw = json.dumps(
        {
            "reply": "こんにちは",
            "session": {"title": "挨拶", "summary": "挨拶を交わした"},
            "memory_updates": [{"op": "add", "section": "好み", "text": "朝型"}],
        }
    )
    response = parse_response(raw)
    assert response.reply == "こんにちは"
    assert response.session.title == "挨拶"
    assert response.memory_updates == [MemoryUpdate("add", "好み", "朝型")]


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        json.dumps({"reply": ""}),
        json.dumps({"reply": "x", "memory_updates": [{"op": "upsert", "section": "a", "text": "b"}]}),
    ],
)
def test_invalid_response_raises(raw):
    with pytest.raises(ResponseError):
        parse_response(raw)


def test_fallback_response_keeps_raw_text_without_updates():
    response = fallback_response("  生の応答  ")
    assert response.reply == "生の応答"
    assert response.parsed is False
    assert response.memory_updates == []
