from dataclasses import dataclass

CARD_VERSION = 1
APPROVAL_ACTIONS: tuple[str, ...] = ("approve", "reject", "request_changes", "ask_evidence")


@dataclass(frozen=True)
class CardHeader:
    card_type: str
    card_id: str
    idempotency_key: str
    version: int = CARD_VERSION


@dataclass(frozen=True)
class QuestionCard:
    header: CardHeader
    question: str
    why: str
    needed_from: str
    options: tuple[str, ...]
    deadline: str | None
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class ApprovalCard:
    header: CardHeader
    action: str
    rationale: str
    risk: str
    required_role: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class ArtifactCard:
    header: CardHeader
    kind: str
    summary: str
    artifact_ref: str
    artifact_hash: str | None
    sensitivity: str
    review_status: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class DigestItem:
    summary: str
    source_refs: tuple[str, ...]
    verified: bool = True


@dataclass(frozen=True)
class WeeklyDigestCard:
    header: CardHeader
    project: str
    period_start: str
    period_end: str
    review_status: str
    progress: tuple[DigestItem, ...]
    failed_runs: tuple[DigestItem, ...]
    new_evidence: tuple[DigestItem, ...]
    decisions: tuple[DigestItem, ...]
    blocked: tuple[DigestItem, ...]
    next_actions: tuple[DigestItem, ...]


def make_card_header(card_type: str, card_id: str, idempotency_key: str) -> CardHeader:
    if not card_type or not card_id or not idempotency_key:
        raise ValueError("card_type, card_id, and idempotency_key are required")
    return CardHeader(card_type=card_type, card_id=card_id, idempotency_key=idempotency_key)


def render_question_card(card: QuestionCard) -> str:
    lines = _render_header(card.header, title="Question")
    lines.extend(
        [
            f"**Question:** {_clean_inline(card.question)}",
            f"**Why:** {_clean_inline(card.why)}",
            f"**Needed from:** {_clean_inline(card.needed_from)}",
        ],
    )
    if card.options:
        lines.append("**Options:**")
        lines.extend(
            f"{index}. {_clean_inline(option)}"
            for index, option in enumerate(card.options, start=1)
        )
    if card.deadline:
        lines.append(f"**Deadline:** {_clean_inline(card.deadline)}")
    lines.append(_render_refs("Evidence", card.evidence_refs))
    return "\n".join(lines)


def render_approval_card(card: ApprovalCard) -> str:
    lines = _render_header(card.header, title="Approval request")
    lines.extend(
        [
            f"**Action:** {_clean_inline(card.action)}",
            f"**Risk:** {_clean_inline(card.risk)}",
            f"**Required role:** {_clean_inline(card.required_role)}",
            f"**Rationale:** {_clean_inline(card.rationale)}",
            _render_refs("Evidence", card.evidence_refs),
            "**Actions:** " + ", ".join(f"`{action}`" for action in APPROVAL_ACTIONS),
        ],
    )
    return "\n".join(lines)


def render_artifact_card(card: ArtifactCard) -> str:
    lines = _render_header(card.header, title="Artifact")
    lines.extend(
        [
            f"**Kind:** {_clean_inline(card.kind)}",
            f"**Summary:** {_clean_inline(card.summary)}",
            f"**Reference:** `{_clean_inline(card.artifact_ref)}`",
        ],
    )
    if card.artifact_hash:
        lines.append(f"**Hash:** `{_clean_inline(card.artifact_hash)}`")
    lines.extend(
        [
            f"**Sensitivity:** {_clean_inline(card.sensitivity)}",
            f"**Review status:** {_clean_inline(card.review_status)}",
            _render_refs("Evidence", card.evidence_refs),
        ],
    )
    return "\n".join(lines)


def render_weekly_digest_card(card: WeeklyDigestCard) -> str:
    lines = _render_header(card.header, title="Weekly digest")
    lines.extend(
        [
            f"**Project:** {_clean_inline(card.project)}",
            f"**Period:** {_clean_inline(card.period_start)} to {_clean_inline(card.period_end)}",
            f"**Review status:** {_clean_inline(card.review_status)}",
        ],
    )
    sections: tuple[tuple[str, tuple[DigestItem, ...]], ...] = (
        ("Progress", card.progress),
        ("Failed runs", card.failed_runs),
        ("New evidence", card.new_evidence),
        ("Decisions", card.decisions),
        ("Blocked", card.blocked),
        ("Next actions", card.next_actions),
    )
    for title, items in sections:
        lines.append(f"### {title}")
        if not items:
            lines.append("- None")
            continue
        lines.extend(_render_digest_item(item) for item in items)
    return "\n".join(lines)


def _render_header(header: CardHeader, *, title: str) -> list[str]:
    return [
        f"## {title}",
        "<!-- sciforge-card "
        f"card_type={header.card_type} "
        f"card_id={header.card_id} "
        f"version={header.version} "
        f"idempotency_key={header.idempotency_key} "
        "-->",
    ]


def _render_digest_item(item: DigestItem) -> str:
    marker = "" if item.verified else " **unverified**"
    refs = _render_refs("sources", item.source_refs)
    return f"- {_clean_inline(item.summary)}{marker}; {refs}"


def _render_refs(label: str, refs: tuple[str, ...]) -> str:
    if not refs:
        return f"**{label}:** none"
    return f"**{label}:** " + ", ".join(f"`{_clean_inline(ref)}`" for ref in refs)


def _clean_inline(value: str) -> str:
    return " ".join(value.strip().split())
