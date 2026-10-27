import math
import re
from collections import Counter
from collections.abc import Sequence

# ASCII words stay whole; runs of Japanese characters are split into bigrams.
_TOKEN = re.compile(
    r"[a-z0-9_]+"
    r"|[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f]+"
)


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _TOKEN.finditer(text.lower()):
        run = match.group()
        if run.isascii() or len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


class BM25:
    """Okapi BM25 with the non-negative Lucene IDF variant."""

    def __init__(self, documents: Sequence[str], k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._docs = [Counter(tokenize(doc)) for doc in documents]
        self._lengths = [sum(counts.values()) for counts in self._docs]
        total = len(self._docs)
        self._avgdl = (sum(self._lengths) / total) if total else 0.0

        document_frequency: Counter[str] = Counter()
        for counts in self._docs:
            document_frequency.update(counts.keys())
        self._idf = {
            term: math.log(1 + (total - df + 0.5) / (df + 0.5))
            for term, df in document_frequency.items()
        }

    def normalized_scores(self, query: str, min_terms: int = 2) -> list[float]:
        """Scores in [0, 1], capped at 1.

        The reference is the score of an average-length document containing each known
        query term once (the sum of their IDFs). Terms absent from the corpus are ignored,
        so common function words in the query do not dilute the score. A document must
        match at least `min_terms` distinct known terms to score above zero.
        """
        known = [term for term in set(tokenize(query)) if term in self._idf]
        reference = sum(self._idf[term] for term in known)
        if not known or reference == 0:
            return [0.0] * len(self._docs)
        raw = self.scores(query)
        results: list[float] = []
        for counts, score in zip(self._docs, raw):
            matched = sum(1 for term in known if term in counts)
            results.append(min(1.0, score / reference) if matched >= min_terms else 0.0)
        return results

    def scores(self, query: str) -> list[float]:
        terms = set(tokenize(query))
        results: list[float] = []
        for counts, length in zip(self._docs, self._lengths):
            score = 0.0
            norm = self._k1 * (1 - self._b + self._b * length / self._avgdl) if self._avgdl else 0.0
            for term in terms:
                frequency = counts.get(term, 0)
                if frequency:
                    score += self._idf[term] * frequency * (self._k1 + 1) / (frequency + norm)
            results.append(score)
        return results
