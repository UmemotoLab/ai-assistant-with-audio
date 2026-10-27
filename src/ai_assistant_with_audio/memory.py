import os
import re
from dataclasses import dataclass
from pathlib import Path

from ai_assistant_with_audio.bm25 import BM25
from ai_assistant_with_audio.config import MEMORY_TOP_K
from ai_assistant_with_audio.response import MemoryUpdate

_HEADING = re.compile(r"^##\s+(.*)$")
_BLANK_LINE = re.compile(r"\n\s*\n")
TEMPLATE = "# Memory Bank\n"


@dataclass
class _Section:
    heading: str
    body: str = ""


def _paragraphs(body: str) -> list[str]:
    return [block.strip() for block in _BLANK_LINE.split(body) if block.strip()]


def _parse(markdown: str) -> tuple[str, list[_Section]]:
    """Split markdown into a preamble (incl. the `#` title) and `##` sections."""
    preamble_lines: list[str] = []
    headings: list[str] = []
    bodies: list[list[str]] = []
    current = preamble_lines
    for line in markdown.splitlines():
        match = _HEADING.match(line)
        if match:
            headings.append(match.group(1).strip())
            current = []
            bodies.append(current)
            continue
        current.append(line)
    sections = [_Section(h, "\n".join(b).strip()) for h, b in zip(headings, bodies)]
    return "\n".join(preamble_lines).strip(), sections


def _render(preamble: str, sections: list[_Section]) -> str:
    parts = [preamble] if preamble else []
    parts.extend(f"## {s.heading}\n\n{s.body}".rstrip() for s in sections)
    return "\n\n".join(parts) + "\n"


def _apply_one(sections: list[_Section], update: MemoryUpdate) -> None:
    section = next((s for s in sections if s.heading == update.section), None)
    text = update.text.strip()

    if update.op == "delete":
        if section is None:
            return
        if not text:
            sections.remove(section)
            return
        kept = [p for p in _paragraphs(section.body) if text not in p]
        section.body = "\n\n".join(kept)
        return

    if section is None:
        section = _Section(update.section)
        sections.append(section)
    if update.op == "add":
        section.body = f"{section.body}\n\n{text}".strip()
    elif update.op == "replace":
        section.body = text


class MemoryBank:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _read(self) -> str:
        if not self.path.exists():
            return TEMPLATE
        return self.path.read_text(encoding="utf-8")

    def chunks(self) -> list[str]:
        """Heading + paragraph units used for retrieval."""
        _, sections = _parse(self._read())
        return [
            f"## {section.heading}\n{paragraph}"
            for section in sections
            for paragraph in _paragraphs(section.body)
        ]

    def search(self, query: str, top_k: int = MEMORY_TOP_K) -> str:
        units = self.chunks()
        if not units:
            return ""
        scores = BM25(units).scores(query)
        ranked = sorted(
            (index for index, score in enumerate(scores) if score > 0),
            key=lambda index: scores[index],
            reverse=True,
        )[:top_k]
        return "\n\n".join(units[index] for index in ranked)

    def apply_updates(self, updates: list[MemoryUpdate]) -> None:
        if not updates:
            return
        preamble, sections = _parse(self._read())
        for update in updates:
            _apply_one(sections, update)
        self._write(_render(preamble, sections))

    def _write(self, content: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, self.path)
