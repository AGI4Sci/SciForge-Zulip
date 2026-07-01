from dataclasses import dataclass


@dataclass(frozen=True)
class DigestSource:
    ref: str
    summary: str
    verified: bool = True


@dataclass(frozen=True)
class WeeklyDigestDraft:
    project_id: str
    period_start: str
    period_end: str
    progress: tuple[DigestSource, ...]
    failed_runs: tuple[DigestSource, ...]
    new_evidence: tuple[DigestSource, ...]
    decisions: tuple[DigestSource, ...]
    blocked: tuple[DigestSource, ...]
    next_actions: tuple[DigestSource, ...]


SECTION_TITLES: tuple[tuple[str, str], ...] = (
    ("progress", "Progress"),
    ("failed_runs", "Failed runs"),
    ("new_evidence", "New evidence"),
    ("decisions", "Decisions"),
    ("blocked", "Blocked"),
    ("next_actions", "Next actions"),
)


def build_weekly_digest_draft(
    *,
    project_id: str,
    period_start: str,
    period_end: str,
    ledger_events: list[dict[str, object]],
    evidence_claims: list[dict[str, object]],
    paper_radar_items: list[dict[str, object]],
    runtime_summaries: list[dict[str, object]],
) -> WeeklyDigestDraft:
    progress = tuple(
        _source_from_mapping(event, "event_id", "summary", default_ref_prefix="ledger")
        for event in ledger_events
        if event.get("digest_section") == "progress"
    )
    failed_runs = tuple(
        _source_from_mapping(event, "event_id", "summary", default_ref_prefix="ledger")
        for event in ledger_events
        if event.get("digest_section") == "failed_runs"
    )
    decisions = tuple(
        _source_from_mapping(event, "event_id", "summary", default_ref_prefix="ledger")
        for event in ledger_events
        if event.get("digest_section") == "decisions"
    )
    blocked = tuple(
        _source_from_mapping(summary, "thread_id", "summary", default_ref_prefix="runtime")
        for summary in runtime_summaries
        if summary.get("blocked") is True
    )
    next_actions = tuple(
        _source_from_mapping(summary, "thread_id", "next_action", default_ref_prefix="runtime")
        for summary in runtime_summaries
        if summary.get("next_action")
    )

    evidence_sources = [
        _source_from_mapping(claim, "claim_id", "summary", default_ref_prefix="evidence")
        for claim in evidence_claims
    ]
    paper_sources = [
        _source_from_mapping(item, "paper_id", "summary", default_ref_prefix="paper")
        for item in paper_radar_items
    ]

    return WeeklyDigestDraft(
        project_id=project_id,
        period_start=period_start,
        period_end=period_end,
        progress=progress,
        failed_runs=failed_runs,
        new_evidence=tuple(evidence_sources + paper_sources),
        decisions=decisions,
        blocked=blocked,
        next_actions=next_actions,
    )


def _source_from_mapping(
    data: dict[str, object],
    ref_key: str,
    summary_key: str,
    *,
    default_ref_prefix: str,
) -> DigestSource:
    raw_ref = data.get(ref_key)
    ref = str(raw_ref) if raw_ref is not None else f"{default_ref_prefix}:unknown"
    raw_summary = data.get(summary_key)
    summary = str(raw_summary) if raw_summary is not None else "(missing summary)"
    verified = data.get("verified", True) is True
    return DigestSource(ref=ref, summary=summary, verified=verified)

