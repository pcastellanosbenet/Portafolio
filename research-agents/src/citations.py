"""Citation validation and sanitization of researcher output."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import BaseMessage, ToolMessage

from src.models import Claim, FinalReport, ResearchOutput, Source

_SOURCE_ID_RE = re.compile(r"src_[0-9a-f]{12}")
_FULLWIDTH_CITATION_RE = re.compile(r"[【\[]\[?\s*\^?\s*(src_[0-9a-f]{12})\s*[】\]]\]?")

def normalize_citations(markdown: str) -> str:
    """Normalize full-width, double-bracket and footnote citation variants."""
    return _FULLWIDTH_CITATION_RE.sub(lambda match: f"[{match.group(1)}]", markdown)



@dataclass(frozen=True)
class CitationValidation:
    issues: list[str] = field(default_factory=list)
    unknown_source_ids: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.issues


def validate_citations(report: FinalReport) -> CitationValidation:
    """Check claims and Markdown references against the report sources."""
    known = {source.source_id for source in report.sources}
    issues: list[str] = []
    unknown: list[str] = []
    for claim in report.claims:
        if not claim.source_ids:
            issues.append(f"Claim {claim.claim_id} has no sources.")
            continue
        missing = [source_id for source_id in claim.source_ids if source_id not in known]
        if missing:
            unknown.extend(missing)
            issues.append(f"Claim {claim.claim_id} cites unknown sources: {', '.join(missing)}.")

    referenced = _SOURCE_ID_RE.findall(normalize_citations(report.answer_markdown))
    unknown_refs = [source_id for source_id in referenced if source_id not in known]
    if unknown_refs:
        unknown.extend(unknown_refs)
        issues.append(
            "Report cites source ids that are not in the source list: "
            + ", ".join(sorted(set(unknown_refs)))
            + "."
        )
    return CitationValidation(
        issues=list(dict.fromkeys(issues)),
        unknown_source_ids=list(dict.fromkeys(unknown)),
    )


def _walk_source_dicts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "source_id" in value and "url" in value:
            found.append(value)
        for item in value.values():
            found.extend(_walk_source_dicts(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_source_dicts(item))
    return found


def _parse_tool_content(content: Any) -> Any:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None
    return content


def _source_from_tool_dict(raw: dict[str, Any]) -> Source | None:
    source_id = str(raw.get("source_id") or "").strip()
    url = str(raw.get("url") or "").strip()
    if not source_id or not url:
        return None
    kind = str(raw.get("kind") or "web")
    if kind not in {"web", "arxiv", "wikipedia", "other"}:
        kind = "web"
    metadata = raw.get("metadata")
    return Source(
        source_id=source_id,
        url=url,
        title=str(raw.get("title") or url).strip(),
        kind=kind,  # type: ignore[arg-type]
        snippet=str(raw.get("snippet") or raw.get("text") or "").strip(),
        metadata={
            str(key): str(value)
            for key, value in (metadata.items() if isinstance(metadata, dict) else [])
        },
    )


def collect_sources_from_messages(messages: list[BaseMessage]) -> dict[str, Source]:
    """Collect every source returned by tools in the conversation."""
    sources: dict[str, Source] = {}
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        payload = _parse_tool_content(message.content)
        for raw in _walk_source_dicts(payload):
            source = _source_from_tool_dict(raw)
            if source is not None:
                sources[source.source_id] = source
    return sources


def sanitize_research_output(
    output: ResearchOutput,
    tool_sources: dict[str, Source],
) -> ResearchOutput:
    """Remove citations and claims that were not actually retrieved by a tool."""
    allowed = set(tool_sources)
    sources = {
        source.source_id: source
        for source in output.sources
        if source.source_id in allowed
    }
    sources.update(tool_sources)

    claims: list[Claim] = []
    gaps = list(output.gaps)
    dropped = 0
    for claim in output.claims:
        valid_ids = [source_id for source_id in claim.source_ids if source_id in allowed]
        if not valid_ids:
            dropped += 1
            unknown = [source_id for source_id in claim.source_ids if source_id not in allowed]
            if unknown:
                gaps.append(
                    f"Claim {claim.claim_id} was dropped because its cited sources "
                    f"were not retrieved: {', '.join(unknown)}."
                )
            else:
                gaps.append(
                    f"Claim {claim.claim_id} was dropped because it had no source."
                )
            continue
        claims.append(claim.model_copy(update={"source_ids": valid_ids}))

    if not sources:
        return output.model_copy(
            update={
                "summary": "No sources were retrieved for this subquestion.",
                "claims": [],
                "sources": [],
                "gaps": list(
                    dict.fromkeys(
                        [
                            *gaps,
                            "No sources were retrieved; unsupported claims were discarded.",
                        ]
                    )
                ),
                "confidence": "low",
            }
        )

    confidence = output.confidence
    if dropped or not claims:
        confidence = "low"
    return output.model_copy(
        update={
            "claims": claims,
            "sources": list(sources.values()),
            "gaps": list(dict.fromkeys(gaps)),
            "confidence": confidence,
        }
    )
