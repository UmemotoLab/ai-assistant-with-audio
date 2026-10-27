import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from secrets import token_hex

from ai_assistant_with_audio.bm25 import BM25
from ai_assistant_with_audio.config import MAX_SESSIONS, RECENT_TURNS

TIME_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


@dataclass(frozen=True)
class Session:
    id: str
    title: str
    created: datetime
    updated: datetime
    summary: str

    @property
    def search_text(self) -> str:
        return f"{self.title}\n{self.summary}"


@dataclass(frozen=True)
class Turn:
    timestamp: str
    user: str
    assistant: str


def _format_summary(session: Session) -> str:
    frontmatter = [
        "---",
        f"id: {json.dumps(session.id, ensure_ascii=False)}",
        f"title: {json.dumps(session.title, ensure_ascii=False)}",
        f"created: {session.created.strftime(TIME_FORMAT)}",
        f"updated: {session.updated.strftime(TIME_FORMAT)}",
        "---",
    ]
    return "\n".join(frontmatter) + f"\n\n{session.summary.strip()}\n"


def _parse_summary(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    fields: dict[str, str] = {}
    end = 0
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                end = index + 1
                break
            key, _, value = lines[index].partition(":")
            fields[key.strip()] = value.strip()
    body = "\n".join(lines[end:]).strip()
    return fields, body


def _load_json_string(value: str) -> str:
    return json.loads(value) if value.startswith('"') else value


class SessionStore:
    def __init__(self, data_dir: Path) -> None:
        self.sessions_dir = Path(data_dir) / "sessions"
        self.archive_dir = Path(data_dir) / "archive"

    def ensure_dirs(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def _summary_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.summary.md"

    def _log_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.log.jsonl"

    def _read(self, path: Path) -> Session | None:
        fields, body = _parse_summary(path.read_text(encoding="utf-8"))
        if "id" not in fields:
            return None
        try:
            return Session(
                id=_load_json_string(fields["id"]),
                title=_load_json_string(fields.get("title", "")),
                created=datetime.strptime(fields["created"], TIME_FORMAT),
                updated=datetime.strptime(fields["updated"], TIME_FORMAT),
                summary=body,
            )
        except (KeyError, ValueError):
            return None

    def load_all(self) -> list[Session]:
        if not self.sessions_dir.exists():
            return []
        sessions = [
            session
            for path in self.sessions_dir.glob("*.summary.md")
            if (session := self._read(path)) is not None
        ]
        return sorted(sessions, key=lambda s: s.updated)

    def get(self, session_id: str) -> Session | None:
        path = self._summary_path(session_id)
        return self._read(path) if path.exists() else None

    def select(self, query: str, threshold: float) -> tuple[Session | None, float]:
        """Return the best-matching session when its normalized BM25 score reaches the threshold."""
        sessions = self.load_all()
        if not sessions:
            return None, 0.0
        scores = BM25([s.search_text for s in sessions]).normalized_scores(query)
        best = max(range(len(sessions)), key=lambda index: scores[index])
        if scores[best] >= threshold:
            return sessions[best], scores[best]
        return None, scores[best]

    def create(self, title: str, summary: str, now: datetime) -> Session:
        self._archive_oldest(MAX_SESSIONS - 1)
        session = Session(
            id=f"{now.strftime('%Y%m%d-%H%M%S')}-{token_hex(2)}",
            title=title.strip(),
            created=now,
            updated=now,
            summary=summary.strip(),
        )
        self.ensure_dirs()
        self._summary_path(session.id).write_text(_format_summary(session), encoding="utf-8")
        self._log_path(session.id).touch()
        return session

    def update_summary(self, session: Session, summary: str, now: datetime) -> Session:
        updated = Session(session.id, session.title, session.created, now, summary.strip())
        self._summary_path(session.id).write_text(_format_summary(updated), encoding="utf-8")
        return updated

    def append_turn(self, session_id: str, user: str, assistant: str, now: datetime) -> None:
        turn = Turn(timestamp=now.strftime(TIME_FORMAT), user=user, assistant=assistant)
        record = {"ts": turn.timestamp, "user": turn.user, "assistant": turn.assistant}
        with self._log_path(session_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def recent_turns(self, count: int = RECENT_TURNS) -> list[Turn]:
        """Return the latest `count` turns across all sessions, oldest first."""
        if not self.sessions_dir.exists():
            return []
        turns = [
            Turn(record["ts"], record["user"], record["assistant"])
            for path in self.sessions_dir.glob("*.log.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
            for record in [json.loads(line)]
        ]
        turns.sort(key=lambda turn: datetime.strptime(turn.timestamp, TIME_FORMAT))
        return turns[-count:] if count > 0 else []

    def _archive_oldest(self, keep: int) -> None:
        """Archive the oldest sessions (summary only) until at most `keep` remain."""
        sessions = self.load_all()
        for session in sessions[: max(0, len(sessions) - keep)]:
            self.ensure_dirs()
            (self.archive_dir / f"{session.id}.summary.md").write_text(
                _format_summary(session), encoding="utf-8"
            )
            self._summary_path(session.id).unlink(missing_ok=True)
            self._log_path(session.id).unlink(missing_ok=True)
