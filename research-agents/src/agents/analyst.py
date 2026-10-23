"""Analyst node: evidence table and coverage gaps."""

from __future__ import annotations

import time

from src.agents.base import AgentServices, compact_sources, json_payload
from src.budget import BudgetExceeded, usage_from_metadata
from src.models import Analysis, EvidenceItem, Note
from src.prompts import messages
from src.state import ResearchState
from src.trace import trace


def fallback_analysis(notes: list[Note]) -> Analysis:
    evidence: list[EvidenceItem] = []
    gaps: list[str] = []
    seen: set[str] = set()
    for note in notes:
        gaps.extend(note.gaps)
        for claim in note.claims:
            if claim.claim_id in seen:
                continue
            seen.add(claim.claim_id)
            evidence.append(
                EvidenceItem(
                    claim_id=claim.claim_id,
                    claim=claim.text,
                    source_ids=claim.source_ids,
                    supported=bool(claim.source_ids),
                )
            )
    if not notes:
        gaps.append("No research notes were collected.")
    return Analysis(
        summary=(
            f"{len(notes)} notes, {len(evidence)} unique claims, "
            f"{sum(1 for item in evidence if item.supported)} supported claims."
        ),
        evidence=evidence,
        gaps=list(dict.fromkeys(gaps)),
    )


def make_analyst(services: AgentServices):
    def analyst(state: ResearchState) -> dict[str, object]:
        notes = state.get("notes", [])
        sources = state.get("sources", {})
        started = time.perf_counter()
        try:
            services.budget.check_llm(state)
            analysis, metadata = services.llm.invoke_structured(
                Analysis,
                messages(
                    "analyst",
                    json_payload(
                        {
                            "question": state["brief"].question,
                            "notes": notes,
                            "sources": compact_sources(sources.values(), snippet_chars=160),
                        }
                    ),
                ),
            )
            usage = usage_from_metadata(metadata, latency_s=time.perf_counter() - started)
            return {
                "analysis": analysis,
                "status": "analyzing",
                "usage": usage,
                "trace": [
                    trace(
                        "analyst",
                        "analysis_created",
                        evidence=len(analysis.evidence),
                        gaps=len(analysis.gaps),
                        model=metadata.model,
                        tokens=usage.total_tokens,
                        latency_s=usage.latency_s,
                        llm_calls=usage.llm_calls,
                    )
                ],
            }
        except BudgetExceeded as exc:
            analysis = fallback_analysis(notes)
            return {
                "analysis": analysis,
                "status": "analyzing",
                "errors": [str(exc)],
                "trace": [trace("analyst", "budget_exhausted", fallback=True, error=str(exc))],
            }
        except Exception as exc:  # noqa: BLE001 - deterministic fallback keeps the run alive
            analysis = fallback_analysis(notes)
            return {
                "analysis": analysis,
                "status": "analyzing",
                "errors": [f"analyst: {type(exc).__name__}: {exc}"],
                "trace": [
                    trace(
                        "analyst",
                        "llm_error",
                        fallback=True,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                ],
            }

    return analyst
