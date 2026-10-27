from ai_assistant_with_audio import speech


def test_split_text_first_chunk_short_and_lossless():
    text = "お兄ちゃん、おはよう！今日はいい天気だね。" + "これは長めの二文目です。" * 30
    chunks = speech.split_text(text)
    assert len(chunks[0]) <= speech.FIRST_CHUNK_MAX_CHARS
    assert "".join(chunks) == text
    assert all(len(c) <= speech.CHUNK_MAX_CHARS + 20 for c in chunks[1:])


def test_split_text_without_punctuation():
    assert speech.split_text("こんにちは") == ["こんにちは"]


def test_start_speech_plays_in_order(monkeypatch):
    import time
    from types import SimpleNamespace

    def fake_synth(api_key, chunk, voice_id):
        time.sleep(0.2 if chunk.startswith("A") else 0)
        return SimpleNamespace(audio=chunk.encode())

    played = []
    monkeypatch.setattr(speech, "synthesize_with_voice_id", fake_synth)
    monkeypatch.setattr(speech, "_play_wav", played.append)
    monkeypatch.setattr(speech, "split_text", lambda text: ["A。", "B。", "C。"])
    speech.start_speech("k", "v", "x").join()
    assert played == [b"A\xe3\x80\x82", b"B\xe3\x80\x82", b"C\xe3\x80\x82"]

