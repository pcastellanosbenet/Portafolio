"""Critic node: citation and coverage verification."""

from __future__ import annotations

import time

from src.agents.base import AgentServices, json_payload
from src.budget import BudgetExceeded, usage_from_metadata
from src.models import Analysis, Claim, Critique, Note, Source
from src.prompts import messages
from src.state import ResearchState
from src.trace import trace


def _claims(notes: list[Note]) -> list[Claim]:
    seen: dict[str, Claim] = {}
    for note in notes:
        for claim in note.claims:
            seen[claim.claim_id] = claim
    return list(seen.values())


def _citation_issues(
    claims: list[Claim],
    sources: dict[str, Source],
) -> tuple[list[str], list[str]]:
    unsupported: list[str] = []
    missing: list[str] = []
    for claim in claims:
        if not claim.source_ids:
            unsupported.append(claim.claim_id)
            continue
        absent = [source_id for source_id in claim.source_ids if source_id not in sources]
        if absent:
            unsupported.append(claim.claim_id)
            missing.extend(absent)
    return list(dict.fromkeys(unsupported)), list(dict.fromkeys(missing))


def fallback_critique(
    notes: list[Note],
    sources: dict[str, Source],
    analysis: Analysis | None,
) -> Critique:
    claims = _claims(notes)
    unsupported, missing = _citation_issues(claims, sources)
    gaps = list(analysis.gaps) if analysis else []
    for note in notes:
        gaps.extend(note.gaps)
    if not claims:
        gaps.append("No supported claims were found.")
    gaps = list(dict.fromkeys(gaps))
    return Critique(
        verdict="revise" if unsupported else "approve",
        gaps=gaps,
        unsupported_claim_ids=unsupported,
        missing_source_ids=missing,
        instructions=(
            "Collect additional evidence for the unsupported claims."
            if unsupported
            else "Proceed to the report writer."
        ),
    )


def enforce_critique(
    critique: Critique,
    notes: list[Note],
    sources: dict[str, Source],
) -> Critique:
    """Apply deterministic citation checks on top of the LLM verdict."""
    claims = _claims(notes)
    unsupported, missing = _citation_issues(claims, sources)
    if not unsupported:
        return critique
    gaps = list(dict.fromkeys([*critique.gaps, "Claims without valid source support."]))
    unsupported_ids = list(dict.fromkeys([*critique.unsupported_claim_ids, *unsupported]))
    missing_ids = list(dict.fromkeys([*critique.missing_source_ids, *missing]))
    return critique.model_copy(
        update={
            "verdict": "revise",
            "gaps": gaps,
            "unsupported_claim_ids": unsupported_ids,
            "missing_source_ids": missing_ids,
            "instructions": critique.instructions
            or "Collect evidence for claims without valid citations.",
        }
    )


def make_critic(services: AgentServices):
    def critic(state: ResearchState) -> dict[str, object]:
        notes = state.get("notes", [])
        sources = state.get("sources", {})
        analysis = state.get("analysis")
        started = time.perf_counter()
        try:
            services.budget.check_llm(state)
            critique, metadata = services.llm.invoke_structured(
                Critique,
                messages(
                    "critic",
                    json_payload(
                        {
                            "question": state["brief"].question,
                            "notes": notes,
                            "sources": list(sources.values()),
                            "analysis": analysis,
                        }
                    ),
                ),
            )
            critique = enforce_critique(critique, notes, sources)
            return {
                "critique": critique,
                "status": "reviewing",
                "usage": usage_from_metadata(metadata, latency_s=time.perf_counter() - started),
                "trace": [
                    trace(
                        "critic",
                        "critique_created",
                        verdict=critique.verdict,
                        unsupported=len(critique.unsupported_claim_ids),
                        gaps=len(critique.gaps),
                        model=metadata.model,
                    )
                ],
            }
        except BudgetExceeded as exc:
            critique = fallback_critique(notes, sources, analysis)
            return {
                "critique": critique,
                "status": "reviewing",
                "errors": [str(exc)],
                "trace": [trace("critic", "budget_exhausted", fallback=True)],
            }
        except Exception as exc:  # noqa: BLE001 - deterministic fallback keeps the run alive
            critique = fallback_critique(notes, sources, analysis)
            return {
                "critique": critique,
                "status": "reviewing",
                "errors": [f"critic: {type(exc).__name__}: {exc}"],
                "trace": [trace("critic", "llm_error", fallback=True)],
            }

    return critic
