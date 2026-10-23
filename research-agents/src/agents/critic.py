"""Critic node: citation and coverage verification."""

from __future__ import annotations

import time

from src.agents.base import AgentServices, compact_notes, compact_sources, json_payload
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
) -> tuple[list[str], list[str], list[str]]:
    supported: list[str] = []
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
            continue
        supported.append(claim.claim_id)
    return (
        list(dict.fromkeys(supported)),
        list(dict.fromkeys(unsupported)),
        list(dict.fromkeys(missing)),
    )


def check_claim_support(
    notes: list[Note],
    sources: dict[str, Source],
) -> tuple[list[str], list[str], list[str]]:
    """Return supported, unsupported and missing source identifiers.

    This is a deterministic structural check: a claim is supported when it has
    at least one citation and every cited ID exists in the retrieved sources.
    It does not verify semantic entailment; that remains a human or judge task.
    """
    return _citation_issues(_claims(notes), sources)


def fallback_critique(
    notes: list[Note],
    sources: dict[str, Source],
    analysis: Analysis | None,
) -> Critique:
    claims = _claims(notes)
    supported, unsupported, missing = _citation_issues(claims, sources)
    gaps = list(analysis.gaps) if analysis else []
    for note in notes:
        gaps.extend(note.gaps)
    if not claims:
        gaps.append("No supported claims were found.")
    gaps = list(dict.fromkeys(gaps))
    return Critique(
        verdict="revise" if unsupported else "approve",
        supported_claim_ids=supported,
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
    supported, unsupported, missing = check_claim_support(notes, sources)
    if not unsupported:
        return critique.model_copy(update={"supported_claim_ids": supported})
    gaps = list(dict.fromkeys([*critique.gaps, "Claims without valid source support."]))
    unsupported_ids = list(dict.fromkeys([*critique.unsupported_claim_ids, *unsupported]))
    supported_ids = [claim_id for claim_id in supported if claim_id not in unsupported_ids]
    missing_ids = list(dict.fromkeys([*critique.missing_source_ids, *missing]))
    return critique.model_copy(
        update={
            "verdict": "revise",
            "supported_claim_ids": supported_ids,
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
                            "notes": compact_notes(notes),
                            "sources": compact_sources(sources.values(), snippet_chars=0),
                            "analysis": analysis,
                        }
                    ),
                ),
            )
            critique = enforce_critique(critique, notes, sources)
            usage = usage_from_metadata(metadata, latency_s=time.perf_counter() - started)
            return {
                "critique": critique,
                "status": "reviewing",
                "usage": usage,
                "trace": [
                    trace(
                        "critic",
                        "critique_created",
                        verdict=critique.verdict,
                        supported=len(critique.supported_claim_ids),
                        unsupported=len(critique.unsupported_claim_ids),
                        gaps=len(critique.gaps),
                        model=metadata.model,
                        tokens=usage.total_tokens,
                        latency_s=usage.latency_s,
                        llm_calls=usage.llm_calls,
                    )
                ],
            }
        except BudgetExceeded as exc:
            critique = fallback_critique(notes, sources, analysis)
            return {
                "critique": critique,
                "status": "reviewing",
                "errors": [str(exc)],
                "trace": [trace("critic", "budget_exhausted", fallback=True, error=str(exc))],
            }
        except Exception as exc:  # noqa: BLE001 - deterministic fallback keeps the run alive
            critique = fallback_critique(notes, sources, analysis)
            return {
                "critique": critique,
                "status": "reviewing",
                "errors": [f"critic: {type(exc).__name__}: {exc}"],
                "trace": [
                    trace(
                        "critic",
                        "llm_error",
                        fallback=True,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                ],
            }

    return critic
