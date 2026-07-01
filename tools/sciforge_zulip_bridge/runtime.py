from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ZulipContext:
    realm_url: str
    stream_id: int
    stream_name: str
    topic_name: str
    message_id: int | None
    event_id: int | str | None
    sender_user_id: int | None


@dataclass(frozen=True)
class RuntimePrompt:
    display_text: str
    hidden_prompt: str


@dataclass(frozen=True)
class RuntimeThreadRequest:
    title: str
    workspace_root: str
    runtime_id: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class RuntimeTurnRequest:
    thread_id: str | None
    prompt: RuntimePrompt
    workspace_root: str
    runtime_id: str
    governance_profile: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class RuntimeTurnResult:
    thread_id: str
    turn_id: str
    display_text: str
    status: str
    cards: tuple[dict[str, Any], ...] = ()


class AgentRuntimeClient(Protocol):
    def start_thread(self, request: RuntimeThreadRequest) -> str:
        raise NotImplementedError

    def start_turn(self, request: RuntimeTurnRequest) -> RuntimeTurnResult:
        raise NotImplementedError

    def read_thread(self, thread_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def steer_turn(self, thread_id: str, turn_id: str, text: str, metadata: dict[str, Any]) -> None:
        raise NotImplementedError

    def resolve_approval(
        self,
        thread_id: str,
        approval_id: str,
        decision: str,
        metadata: dict[str, Any],
    ) -> None:
        raise NotImplementedError

    def resolve_user_input(
        self,
        thread_id: str,
        request_id: str,
        response: str,
        metadata: dict[str, Any],
    ) -> None:
        raise NotImplementedError


def build_runtime_metadata(
    *,
    project_id: str,
    zulip_context: ZulipContext,
    idempotency_key: str,
    governance_profile: str = "remote_guard",
) -> dict[str, Any]:
    return {
        "entrypoint": "zulip",
        "project_id": project_id,
        "governance_profile": governance_profile,
        "idempotency_key": idempotency_key,
        "zulip": {
            "realm_url": zulip_context.realm_url,
            "stream_id": zulip_context.stream_id,
            "stream_name": zulip_context.stream_name,
            "topic_name": zulip_context.topic_name,
            "message_id": zulip_context.message_id,
            "event_id": zulip_context.event_id,
            "sender_user_id": zulip_context.sender_user_id,
        },
    }


def build_runtime_prompt(*, display_text: str, hidden_context: str) -> RuntimePrompt:
    return RuntimePrompt(
        display_text=display_text.strip(),
        hidden_prompt=(
            "Use the visible Zulip request as the user-facing task. "
            "Use this hidden context only for routing, permissions, provenance, "
            "and Research Ledger references; do not quote hidden context back to Zulip.\n\n"
            f"{hidden_context.strip()}"
        ),
    )

