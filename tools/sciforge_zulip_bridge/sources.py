from dataclasses import dataclass
from typing import Protocol

from tools.sciforge_zulip_bridge.digest import WeeklyDigestDraft, build_weekly_digest_draft
from tools.sciforge_zulip_bridge.ledger import ResearchLedger


class EvidenceDagSource(Protocol):
    def list_claims(
        self,
        *,
        project_id: str,
        period_start: str,
        period_end: str,
    ) -> list[dict[str, object]]:
        raise NotImplementedError


class PaperRadarSource(Protocol):
    def list_digest_items(
        self,
        *,
        project_id: str,
        period_start: str,
        period_end: str,
    ) -> list[dict[str, object]]:
        raise NotImplementedError


class RuntimeSummarySource(Protocol):
    def list_thread_summaries(
        self,
        *,
        project_id: str,
        period_start: str,
        period_end: str,
    ) -> list[dict[str, object]]:
        raise NotImplementedError


@dataclass(frozen=True)
class WeeklyDigestSources:
    evidence_dag: EvidenceDagSource
    paper_radar: PaperRadarSource
    runtime: RuntimeSummarySource


def query_ledger_events_for_period(
    ledger: ResearchLedger,
    *,
    project_id: str,
    period_start: str,
    period_end: str,
) -> list[dict[str, object]]:
    events = ledger.list_events(project_id=project_id, limit=10_000)
    period_events = []
    for event in events:
        if not period_start <= str(event["created_at"])[:10] <= period_end:
            continue
        payload = event.get("payload")
        if isinstance(payload, dict):
            period_events.append({**event, **payload})
        else:
            period_events.append(event)
    return period_events


def collect_weekly_digest_draft(
    *,
    project_id: str,
    period_start: str,
    period_end: str,
    ledger: ResearchLedger,
    sources: WeeklyDigestSources,
) -> WeeklyDigestDraft:
    return build_weekly_digest_draft(
        project_id=project_id,
        period_start=period_start,
        period_end=period_end,
        ledger_events=query_ledger_events_for_period(
            ledger,
            project_id=project_id,
            period_start=period_start,
            period_end=period_end,
        ),
        evidence_claims=sources.evidence_dag.list_claims(
            project_id=project_id,
            period_start=period_start,
            period_end=period_end,
        ),
        paper_radar_items=sources.paper_radar.list_digest_items(
            project_id=project_id,
            period_start=period_start,
            period_end=period_end,
        ),
        runtime_summaries=sources.runtime.list_thread_summaries(
            project_id=project_id,
            period_start=period_start,
            period_end=period_end,
        ),
    )
