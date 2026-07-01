import hashlib
import time
from dataclasses import dataclass
from typing import Any, Protocol

from tools.sciforge_zulip_bridge.cards import (
    ApprovalCard,
    ArtifactCard,
    CardHeader,
    QuestionCard,
    WeeklyDigestCard,
    render_approval_card,
    render_artifact_card,
    render_question_card,
    render_weekly_digest_card,
)
from tools.sciforge_zulip_bridge.config import BridgeConfig
from tools.sciforge_zulip_bridge.ledger import (
    CardLink,
    DeliveryRecord,
    LedgerEvent,
    ResearchLedger,
    ThreadLink,
)
from tools.sciforge_zulip_bridge.policy import RolePolicy
from tools.sciforge_zulip_bridge.runtime import (
    AgentRuntimeClient,
    RuntimeTurnRequest,
    ZulipContext,
    build_runtime_metadata,
    build_runtime_prompt,
)
from tools.sciforge_zulip_bridge.zulip_client import ZulipMessageTarget, ZulipSendResult


@dataclass(frozen=True)
class ZulipMessageEvent:
    event_id: int | str
    message_id: int
    stream_id: int
    stream_name: str
    topic_name: str
    sender_user_id: int
    sender_email: str
    content: str
    trigger: str = "event_queue"
    reply_to_message_id: int | None = None


@dataclass(frozen=True)
class ZulipReactionEvent:
    event_id: int | str
    message_id: int
    user_id: int
    emoji_name: str
    op: str


@dataclass(frozen=True)
class ZulipMessageEditEvent:
    event_id: int | str
    message_id: int
    user_id: int | None
    rendering_only: bool
    content: str | None
    topic_name: str | None


class ZulipClient(Protocol):
    def send_stream_message(self, target: ZulipMessageTarget, content: str) -> ZulipSendResult:
        raise NotImplementedError

    def update_message(
        self,
        message_id: int,
        content: str,
        *,
        prev_content_sha256: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError


class SciForgeZulipBridge:
    def __init__(
        self,
        *,
        config: BridgeConfig,
        ledger: ResearchLedger,
        runtime: AgentRuntimeClient,
        zulip: ZulipClient,
        role_policy: RolePolicy | None = None,
    ) -> None:
        self.config = config
        self.ledger = ledger
        self.runtime = runtime
        self.zulip = zulip
        self.role_policy = role_policy or RolePolicy()

    def handle_message_event(self, event: ZulipMessageEvent) -> bool:
        mapping = self.config.mapping_for_stream_id(event.stream_id)
        if event.reply_to_message_id is not None:
            handled_feedback = self._handle_card_reply(event, mapping.project_id)
            if handled_feedback is not None:
                return handled_feedback

        event_key = f"zulip:event:{event.event_id}"
        metadata = self._metadata_for_message_event(event, mapping.project_id, event_key)
        inbound_event = LedgerEvent(
            event_id=f"ledger-{_stable_id(event_key)}",
            project_id=mapping.project_id,
            kind="zulip_message_received",
            actor_kind="zulip_user",
            payload={
                "zulip": metadata["zulip"],
                "content_sha256": _sha256(event.content),
                "trigger": event.trigger,
            },
        )
        if not self.ledger.append_event_once(event_key, inbound_event):
            return False

        if not self._is_agent_trigger(event.content):
            return True

        display_text = self._visible_task_text(event.content)
        hidden_context = (
            f"Project {mapping.project_id}; Zulip stream {event.stream_name} "
            f"({event.stream_id}); topic {event.topic_name}; message {event.message_id}. "
            "Do not stream tool logs or hidden metadata back to Zulip. "
            "Ask questions, request approvals, and publish artifacts only as cards."
        )
        prompt = build_runtime_prompt(display_text=display_text, hidden_context=hidden_context)
        link_key = _thread_link_key(mapping.project_id, event.stream_id, event.topic_name)
        existing_link = self.ledger.get_thread_link(link_key)
        thread_id = str(existing_link["runtime_thread_id"]) if existing_link is not None else None
        result = self.runtime.start_turn(
            RuntimeTurnRequest(
                thread_id=thread_id,
                prompt=prompt,
                workspace_root=mapping.workspace_root,
                runtime_id=mapping.runtime_id,
                governance_profile=self.config.runtime.default_governance_profile,
                metadata=metadata,
            ),
        )
        self.ledger.append_event(
            LedgerEvent(
                event_id=f"ledger-runtime-turn-{_stable_id(event_key)}",
                project_id=mapping.project_id,
                kind="agent_turn_started",
                actor_kind="agent",
                payload={
                    "runtime_id": mapping.runtime_id,
                    "runtime_thread_id": result.thread_id,
                    "runtime_turn_id": result.turn_id,
                    "status": result.status,
                    "zulip_message_id": event.message_id,
                },
            ),
        )
        self.ledger.record_thread_link(
            ThreadLink(
                link_key=link_key,
                project_id=mapping.project_id,
                runtime_id=mapping.runtime_id,
                runtime_thread_id=result.thread_id,
                zulip_stream_id=event.stream_id,
                zulip_topic_name=event.topic_name,
                zulip_root_message_id=event.message_id,
            ),
        )
        self._post_or_record_failure(
            project_id=mapping.project_id,
            target=ZulipMessageTarget(stream=event.stream_name, topic=event.topic_name),
            content=result.display_text,
            idempotency_key=f"zulip:outbound:turn-result:{result.thread_id}:{result.turn_id}",
            ledger_event_kind="agent_turn_completed",
            payload={
                "runtime_thread_id": result.thread_id,
                "runtime_turn_id": result.turn_id,
                "status": result.status,
            },
        )
        return True

    def handle_reaction_event(self, event: ZulipReactionEvent) -> bool:
        event_key = f"zulip:event:{event.event_id}"
        link = self.ledger.get_card_link_by_message_id(event.message_id)
        project_id = str(link["project_id"]) if link is not None else "unknown"
        ledger_event = LedgerEvent(
            event_id=f"ledger-{_stable_id(event_key)}",
            project_id=project_id,
            kind="zulip_reaction_received",
            actor_kind="zulip_user",
            payload={
                "message_id": event.message_id,
                "user_id": event.user_id,
                "emoji_name": event.emoji_name,
                "op": event.op,
                "card_id": link["card_id"] if link else None,
            },
        )
        if not self.ledger.append_event_once(event_key, ledger_event):
            return False
        if link is None or event.op != "add":
            return True
        action = _reaction_to_action(event.emoji_name)
        if action is None:
            return True
        action_key = f"zulip:card-action:{link['card_id']}:{action}:{event.user_id}"
        if not self.ledger.record_idempotency(action_key, ledger_event.event_id):
            return False
        if link["card_type"] == "approval":
            decision = self.role_policy.authorize(
                user_id=event.user_id,
                required_role=str(link["required_role"]) if link["required_role"] else None,
            )
            if not decision.allowed:
                self.ledger.append_event(
                    LedgerEvent(
                        event_id=f"ledger-approval-denied-{_stable_id(action_key)}",
                        project_id=project_id,
                        kind="approval_ignored",
                        actor_kind="system",
                        payload={
                            "action": action,
                            "card_id": link["card_id"],
                            "user_id": event.user_id,
                            "reason": decision.reason,
                        },
                    ),
                )
                return True
            if not link["runtime_thread_id"] or not link["runtime_request_id"]:
                return True
            self.runtime.resolve_approval(
                str(link["runtime_thread_id"]),
                str(link["runtime_request_id"]),
                action,
                {
                    "source": "zulip_reaction",
                    "zulip_message_id": event.message_id,
                    "user_id": event.user_id,
                },
            )
            self.ledger.append_event(
                LedgerEvent(
                    event_id=f"ledger-approval-{_stable_id(action_key)}",
                    project_id=project_id,
                    kind="approval_resolved",
                    actor_kind="zulip_user",
                    payload={
                        "action": action,
                        "card_id": link["card_id"],
                        "user_id": event.user_id,
                    },
                ),
            )
        return True

    def update_card_message(
        self,
        *,
        project_id: str,
        message_id: int,
        content: str,
        idempotency_key: str,
        prev_content_sha256: str | None = None,
    ) -> bool:
        event_id = f"ledger-card-update-{_stable_id(idempotency_key)}"
        if not self.ledger.append_event_once(
            idempotency_key,
            LedgerEvent(
                event_id=event_id,
                project_id=project_id,
                kind="zulip_card_update_intended",
                actor_kind="agent",
                payload={"message_id": message_id, "content_sha256": _sha256(content)},
            ),
        ):
            return False
        try:
            self.zulip.update_message(
                message_id,
                content,
                prev_content_sha256=prev_content_sha256,
            )
        except Exception as error:
            self.ledger.mark_delivery(
                DeliveryRecord(
                    delivery_id=f"delivery-card-update-{_stable_id(idempotency_key)}",
                    idempotency_key=idempotency_key,
                    ledger_event_id=event_id,
                    target=f"message:{message_id}",
                    status="delivery_failed",
                    error=str(error),
                    next_retry_at=str(int(time.time()) + 60),
                ),
            )
            return False
        self.ledger.mark_delivery(
            DeliveryRecord(
                delivery_id=f"delivery-card-update-{_stable_id(idempotency_key)}",
                idempotency_key=idempotency_key,
                ledger_event_id=event_id,
                target=f"message:{message_id}",
                status="delivered",
                zulip_message_id=message_id,
            ),
        )
        return True

    def handle_message_edit_event(self, event: ZulipMessageEditEvent) -> bool:
        if event.rendering_only:
            return True
        event_key = f"zulip:event:{event.event_id}"
        link = self.ledger.get_card_link_by_message_id(event.message_id)
        project_id = str(link["project_id"]) if link is not None else "unknown"
        return self.ledger.append_event_once(
            event_key,
            LedgerEvent(
                event_id=f"ledger-{_stable_id(event_key)}",
                project_id=project_id,
                kind="zulip_message_edited",
                actor_kind="zulip_user" if event.user_id is not None else "system",
                payload={
                    "message_id": event.message_id,
                    "user_id": event.user_id,
                    "topic_name": event.topic_name,
                    "content_sha256": (
                        _sha256(event.content or "") if event.content is not None else None
                    ),
                    "card_id": link["card_id"] if link else None,
                },
            ),
        )

    def post_question_card(
        self,
        *,
        project_id: str,
        target: ZulipMessageTarget,
        card: QuestionCard,
    ) -> int | None:
        return self._post_card(
            project_id=project_id,
            target=target,
            header=card.header,
            content=render_question_card(card),
            runtime_thread_id=None,
            runtime_turn_id=None,
            runtime_request_id=None,
            required_role=card.needed_from,
        )

    def post_approval_card(
        self,
        *,
        project_id: str,
        target: ZulipMessageTarget,
        card: ApprovalCard,
        runtime_thread_id: str,
        runtime_turn_id: str | None,
        runtime_request_id: str,
    ) -> int | None:
        return self._post_card(
            project_id=project_id,
            target=target,
            header=card.header,
            content=render_approval_card(card),
            runtime_thread_id=runtime_thread_id,
            runtime_turn_id=runtime_turn_id,
            runtime_request_id=runtime_request_id,
            required_role=card.required_role,
        )

    def post_artifact_card(
        self,
        *,
        project_id: str,
        target: ZulipMessageTarget,
        card: ArtifactCard,
    ) -> int | None:
        return self._post_card(
            project_id=project_id,
            target=target,
            header=card.header,
            content=render_artifact_card(card),
            runtime_thread_id=None,
            runtime_turn_id=None,
            runtime_request_id=None,
            required_role=None,
        )

    def post_weekly_digest_card(
        self,
        *,
        project_id: str,
        target: ZulipMessageTarget,
        card: WeeklyDigestCard,
    ) -> int | None:
        return self._post_card(
            project_id=project_id,
            target=target,
            header=card.header,
            content=render_weekly_digest_card(card),
            runtime_thread_id=None,
            runtime_turn_id=None,
            runtime_request_id=None,
            required_role="pi",
        )

    def _post_card(
        self,
        *,
        project_id: str,
        target: ZulipMessageTarget,
        header: CardHeader,
        content: str,
        runtime_thread_id: str | None,
        runtime_turn_id: str | None,
        runtime_request_id: str | None,
        required_role: str | None,
    ) -> int | None:
        result = self._post_or_record_failure(
            project_id=project_id,
            target=target,
            content=content,
            idempotency_key=header.idempotency_key,
            ledger_event_kind=f"{header.card_type}_card_posted",
            payload={
                "card_id": header.card_id,
                "card_type": header.card_type,
                "version": header.version,
            },
        )
        if result is None:
            return None
        self.ledger.record_card_link(
            CardLink(
                card_id=header.card_id,
                card_type=header.card_type,
                project_id=project_id,
                runtime_thread_id=runtime_thread_id,
                runtime_turn_id=runtime_turn_id,
                runtime_request_id=runtime_request_id,
                zulip_message_id=result,
                required_role=required_role,
            ),
        )
        return result

    def _post_or_record_failure(
        self,
        *,
        project_id: str,
        target: ZulipMessageTarget,
        content: str,
        idempotency_key: str,
        ledger_event_kind: str,
        payload: dict[str, Any],
    ) -> int | None:
        ledger_event_id = f"ledger-outbound-{_stable_id(idempotency_key)}"
        self.ledger.append_event_once(
            idempotency_key,
            LedgerEvent(
                event_id=ledger_event_id,
                project_id=project_id,
                kind=ledger_event_kind,
                actor_kind="agent",
                payload={**payload, "target_stream": target.stream, "target_topic": target.topic},
            ),
        )
        delivery_id = f"delivery-{_stable_id(idempotency_key)}"
        try:
            result = self.zulip.send_stream_message(target, content)
        except Exception as error:
            self.ledger.mark_delivery(
                DeliveryRecord(
                    delivery_id=delivery_id,
                    idempotency_key=idempotency_key,
                    ledger_event_id=ledger_event_id,
                    target=f"{target.stream}/{target.topic}",
                    status="delivery_failed",
                    error=str(error),
                    next_retry_at=str(int(time.time()) + 60),
                ),
            )
            return None
        self.ledger.mark_delivery(
            DeliveryRecord(
                delivery_id=delivery_id,
                idempotency_key=idempotency_key,
                ledger_event_id=ledger_event_id,
                target=f"{target.stream}/{target.topic}",
                status="delivered",
                zulip_message_id=result.message_id,
            ),
        )
        return result.message_id

    def _metadata_for_message_event(
        self,
        event: ZulipMessageEvent,
        project_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return build_runtime_metadata(
            project_id=project_id,
            zulip_context=ZulipContext(
                realm_url=self.config.bot.realm_url,
                stream_id=event.stream_id,
                stream_name=event.stream_name,
                topic_name=event.topic_name,
                message_id=event.message_id,
                event_id=event.event_id,
                sender_user_id=event.sender_user_id,
            ),
            idempotency_key=idempotency_key,
            governance_profile=self.config.runtime.default_governance_profile,
        )

    def _handle_card_reply(self, event: ZulipMessageEvent, project_id: str) -> bool | None:
        assert event.reply_to_message_id is not None
        link = self.ledger.get_card_link_by_message_id(event.reply_to_message_id)
        if link is None or link["card_type"] != "question":
            return None
        event_key = f"zulip:event:{event.event_id}"
        ledger_event = LedgerEvent(
            event_id=f"ledger-{_stable_id(event_key)}",
            project_id=project_id,
            kind="feedback_received",
            actor_kind="zulip_user",
            payload={
                "card_id": link["card_id"],
                "message_id": event.message_id,
                "reply_to_message_id": event.reply_to_message_id,
                "sender_user_id": event.sender_user_id,
                "content_sha256": _sha256(event.content),
            },
        )
        if not self.ledger.append_event_once(event_key, ledger_event):
            return False
        if link["runtime_thread_id"] and link["runtime_request_id"]:
            self.runtime.resolve_user_input(
                str(link["runtime_thread_id"]),
                str(link["runtime_request_id"]),
                event.content,
                {
                    "source": "zulip_reply",
                    "zulip_message_id": event.message_id,
                    "reply_to_message_id": event.reply_to_message_id,
                    "sender_user_id": event.sender_user_id,
                },
            )
        return True

    def _is_agent_trigger(self, content: str) -> bool:
        return (
            "@**SciForge Agent**" in content
            or "@SciForge Agent" in content
            or content.strip().startswith("/sciforge")
        )

    def _visible_task_text(self, content: str) -> str:
        return (
            content.replace("@**SciForge Agent**", "")
            .replace("@SciForge Agent", "")
            .removeprefix("/sciforge")
            .strip()
        )


def _thread_link_key(project_id: str, stream_id: int, topic_name: str) -> str:
    return f"{project_id}:{stream_id}:{topic_name}"


def _reaction_to_action(emoji_name: str) -> str | None:
    normalized = emoji_name.lower().replace("-", "_")
    if normalized in {"white_check_mark", "check", "+1", "thumbs_up", "approve"}:
        return "approve"
    if normalized in {"x", "cross_mark", "-1", "thumbs_down", "reject"}:
        return "reject"
    if normalized in {"memo", "pencil", "request_changes"}:
        return "request_changes"
    if normalized in {"mag", "mag_right", "ask_evidence", "question"}:
        return "ask_evidence"
    return None


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
