"""Text normalisation, tokenisation and small deterministic helpers."""

from __future__ import annotations

import re
import unicodedata

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[._/\-][a-z0-9]+)*", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"[ \t]+")
MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

# Very small list: technical documents contain many legitimate short words.
STOPWORDS = {
    "a",
    "al",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "con",
    "de",
    "del",
    "el",
    "en",
    "es",
    "for",
    "from",
    "in",
    "is",
    "it",
    "la",
    "las",
    "lo",
    "los",
    "of",
    "on",
    "or",
    "para",
    "por",
    "que",
    "se",
    "the",
    "to",
    "un",
    "una",
    "with",
}


def normalize_text(text: str) -> str:
    """Normalise unicode, soft hyphens and whitespace without changing wording."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00ad", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = WHITESPACE_RE.sub(" ", text)
    text = MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def clean_cell(text: str) -> str:
    """Normalise a PDF table cell and collapse internal newlines."""
    return normalize_text(text or "").replace("\n", " ").strip()


def slugify(text: str, max_length: int = 120) -> str:
    """Create a stable, URL-safe identifier from a filename or title."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:max_length].strip("-")


def tokenize(text: str) -> list[str]:
    """Tokenise technical text while preserving identifiers such as DPT 1.001.

    Full identifiers are kept and their alphabetic parts are also emitted. This
    helps BM25 match both ``PID_LOAD_STATE_CONTROL`` and ``load state control``.
    """
    text = normalize_text(text)
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    text = text.lower()
    tokens: list[str] = []
    for raw_token in TOKEN_RE.findall(text):
        if raw_token not in STOPWORDS and len(raw_token) > 1:
            tokens.append(raw_token)
        if any(char.isalpha() for char in raw_token):
            for part in re.split(r"[._/\-]+", raw_token):
                if len(part) > 1 and part not in STOPWORDS:
                    tokens.append(part)
    return tokens


def estimate_tokens(text: str) -> int:
    """Cheap token estimate used only for context budgeting."""
    return max(1, round(len(text) / 4))


def unique_preserve_order(values: list[str]) -> list[str]:
    """Deduplicate strings while preserving their first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def truncate(text: str, max_chars: int) -> str:
    """Truncate text at a word boundary."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.") + "…"
