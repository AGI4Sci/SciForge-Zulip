import json
import tempfile
from pathlib import Path
from typing import Any
from unittest import TestCase

from tools.sciforge_zulip_bridge.bridge import (
    SciForgeZulipBridge,
    ZulipMessageEditEvent,
    ZulipMessageEvent,
    ZulipReactionEvent,
)
from tools.sciforge_zulip_bridge.cards import (
    ApprovalCard,
    CardHeader,
    DigestItem,
    QuestionCard,
    WeeklyDigestCard,
    render_approval_card,
    render_weekly_digest_card,
)
from tools.sciforge_zulip_bridge.config import (
    BridgeConfig,
    RuntimeConfig,
    StreamMapping,
    ZulipBotConfig,
    load_redacted_config_dict,
)
from tools.sciforge_zulip_bridge.digest import build_weekly_digest_draft
from tools.sciforge_zulip_bridge.events import (
    message_edit_event_from_event_queue,
    message_event_from_event_queue,
    message_event_from_outgoing_webhook,
    reaction_event_from_event_queue,
)
from tools.sciforge_zulip_bridge.ledger import CardLink, LedgerEvent, ResearchLedger
from tools.sciforge_zulip_bridge.policy import RolePolicy
from tools.sciforge_zulip_bridge.runtime import (
    AgentRuntimeClient,
    RuntimeThreadRequest,
    RuntimeTurnRequest,
    RuntimeTurnResult,
)
from tools.sciforge_zulip_bridge.sources import WeeklyDigestSources, collect_weekly_digest_draft
from tools.sciforge_zulip_bridge.zulip_client import ZulipMessageTarget, ZulipSendResult


class FakeRuntime(AgentRuntimeClient):
    def __init__(self) -> None:
        self.turns: list[RuntimeTurnRequest] = []
        self.resolved_approvals: list[tuple[str, str, str, dict[str, Any]]] = []
        self.resolved_user_inputs: list[tuple[str, str, str, dict[str, Any]]] = []

    def start_thread(self, request: RuntimeThreadRequest) -> str:
        return "thread-created"

    def start_turn(self, request: RuntimeTurnRequest) -> RuntimeTurnResult:
        self.turns.append(request)
        return RuntimeTurnResult(
            thread_id=request.thread_id or "thread-1",
            turn_id="turn-1",
            display_text="SciForge accepted the task.",
            status="running",
        )

    def read_thread(self, thread_id: str) -> dict[str, Any]:
        return {"id": thread_id}

    def steer_turn(
        self,
        thread_id: str,
        turn_id: str,
        text: str,
        metadata: dict[str, Any],
    ) -> None:
        raise AssertionError("not used in this test")

    def resolve_approval(
        self,
        thread_id: str,
        approval_id: str,
        decision: str,
        metadata: dict[str, Any],
    ) -> None:
        self.resolved_approvals.append((thread_id, approval_id, decision, metadata))

    def resolve_user_input(
        self,
        thread_id: str,
        request_id: str,
        response: str,
        metadata: dict[str, Any],
    ) -> None:
        self.resolved_user_inputs.append((thread_id, request_id, response, metadata))


class FakeZulip:
    def __init__(self) -> None:
        self.sent: list[tuple[ZulipMessageTarget, str]] = []
        self.updated: list[tuple[int, str, str | None]] = []

    def send_stream_message(self, target: ZulipMessageTarget, content: str) -> ZulipSendResult:
        self.sent.append((target, content))
        return ZulipSendResult(message_id=10_000 + len(self.sent), raw={"result": "success"})

    def update_message(
        self,
        message_id: int,
        content: str,
        *,
        prev_content_sha256: str | None = None,
    ) -> dict[str, Any]:
        self.updated.append((message_id, content, prev_content_sha256))
        return {"result": "success"}


class SciforgeZulipBridgeTests(TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.ledger = ResearchLedger(Path(self.tmpdir.name) / "ledger.sqlite3")
        self.runtime = FakeRuntime()
        self.zulip = FakeZulip()
        self.config = BridgeConfig(
            upstream_zulip_commit="d2f48ffafdceb62d07933484dad5daba89810888",
            shallow_clone=True,
            require_full_history_before_release=True,
            ledger_path=str(Path(self.tmpdir.name) / "ledger.sqlite3"),
            bot=ZulipBotConfig(
                realm_url="https://zulip.example.com",
                bot_email="sciforge-bot@example.com",
                bot_api_key_env="SCIFORGE_ZULIP_BOT_API_KEY",
                bot_user_id=42,
            ),
            runtime=RuntimeConfig(
                base_url="http://127.0.0.1:39100",
                token_env="SCIFORGE_RUNTIME_TOKEN",
            ),
            stream_mappings=(
                StreamMapping(
                    zulip_stream_id=7,
                    zulip_stream_name="protein-design",
                    project_id="project-1",
                    workspace_root="/workspace/project-1",
                ),
            ),
        )
        self.bridge = SciForgeZulipBridge(
            config=self.config,
            ledger=self.ledger,
            runtime=self.runtime,
            zulip=self.zulip,
            role_policy=RolePolicy({99: {"pi"}}),
        )

    def tearDown(self) -> None:
        self.ledger.close()
        self.tmpdir.cleanup()

    def test_message_trigger_starts_runtime_turn_once(self) -> None:
        event = ZulipMessageEvent(
            event_id=100,
            message_id=500,
            stream_id=7,
            stream_name="protein-design",
            topic_name="hypothesis-1",
            sender_user_id=11,
            sender_email="scientist@example.com",
            content="@**SciForge Agent** summarize the failed runs",
        )

        self.assertTrue(self.bridge.handle_message_event(event))
        self.assertFalse(self.bridge.handle_message_event(event))

        self.assertEqual(len(self.runtime.turns), 1)
        turn = self.runtime.turns[0]
        self.assertEqual(turn.governance_profile, "remote_guard")
        self.assertEqual(turn.metadata["zulip"]["message_id"], 500)
        self.assertEqual(turn.prompt.display_text, "summarize the failed runs")
        self.assertIn("Do not stream tool logs", turn.prompt.hidden_prompt)
        self.assertEqual(len(self.zulip.sent), 1)
        self.assertEqual(self.ledger.health_summary()["ledger_events"], 3)

    def test_reaction_resolves_approval_once(self) -> None:
        card = ApprovalCard(
            header=CardHeader(
                card_type="approval",
                card_id="approval-card-1",
                idempotency_key="zulip:outbound:approval:approval-card-1:1",
            ),
            action="Run high-budget analysis",
            rationale="Needs PI approval",
            risk="high",
            required_role="pi",
            evidence_refs=("EDAG:C-1",),
        )
        message_id = self.bridge.post_approval_card(
            project_id="project-1",
            target=ZulipMessageTarget(stream="protein-design", topic="approvals"),
            card=card,
            runtime_thread_id="thread-1",
            runtime_turn_id="turn-1",
            runtime_request_id="approval-1",
        )
        assert message_id is not None
        reaction = ZulipReactionEvent(
            event_id=200,
            message_id=message_id,
            user_id=99,
            emoji_name="white_check_mark",
            op="add",
        )

        self.assertTrue(self.bridge.handle_reaction_event(reaction))
        self.assertFalse(self.bridge.handle_reaction_event(reaction))

        self.assertEqual(
            self.runtime.resolved_approvals,
            [
                (
                    "thread-1",
                    "approval-1",
                    "approve",
                    {"source": "zulip_reaction", "zulip_message_id": message_id, "user_id": 99},
                ),
            ],
        )
        kinds = [event["kind"] for event in self.ledger.list_events(limit=20)]
        self.assertIn("approval_card_posted", kinds)
        self.assertIn("approval_resolved", kinds)

    def test_approval_reaction_without_required_role_fails_closed(self) -> None:
        card = ApprovalCard(
            header=CardHeader(
                card_type="approval",
                card_id="approval-card-2",
                idempotency_key="zulip:outbound:approval:approval-card-2:1",
            ),
            action="Publish report",
            rationale="External visibility",
            risk="high",
            required_role="pi",
            evidence_refs=("EDAG:C-2",),
        )
        message_id = self.bridge.post_approval_card(
            project_id="project-1",
            target=ZulipMessageTarget(stream="protein-design", topic="approvals"),
            card=card,
            runtime_thread_id="thread-1",
            runtime_turn_id="turn-1",
            runtime_request_id="approval-2",
        )
        assert message_id is not None

        self.assertTrue(
            self.bridge.handle_reaction_event(
                ZulipReactionEvent(
                    event_id=201,
                    message_id=message_id,
                    user_id=12,
                    emoji_name="white_check_mark",
                    op="add",
                ),
            ),
        )
        self.assertEqual(self.runtime.resolved_approvals, [])
        self.assertIn(
            "approval_ignored",
            [event["kind"] for event in self.ledger.list_events(limit=20)],
        )

    def test_question_reply_resolves_user_input(self) -> None:
        message_id = self.bridge.post_question_card(
            project_id="project-1",
            target=ZulipMessageTarget(stream="protein-design", topic="agent-questions"),
            card=QuestionCard(
                header=CardHeader(
                    card_type="question",
                    card_id="question-card-1",
                    idempotency_key="zulip:outbound:question:question-card-1:1",
                ),
                question="Which control should we prioritize?",
                why="Agent needs wet-lab judgement",
                needed_from="scientist",
                options=("RNA quality", "Primer batch"),
                deadline=None,
                evidence_refs=("EDAG:C-3",),
            ),
        )
        assert message_id is not None
        self.ledger.record_card_link(
            CardLink(
                card_id="question-card-1",
                card_type="question",
                project_id="project-1",
                runtime_thread_id="thread-1",
                runtime_turn_id="turn-1",
                runtime_request_id="input-1",
                zulip_message_id=message_id,
                required_role="scientist",
            ),
        )

        self.assertTrue(
            self.bridge.handle_message_event(
                ZulipMessageEvent(
                    event_id=302,
                    message_id=502,
                    stream_id=7,
                    stream_name="protein-design",
                    topic_name="agent-questions",
                    sender_user_id=15,
                    sender_email="scientist@example.com",
                    content="Prioritize RNA quality.",
                    reply_to_message_id=message_id,
                ),
            ),
        )
        self.assertEqual(
            self.runtime.resolved_user_inputs[0][:3],
            ("thread-1", "input-1", "Prioritize RNA quality."),
        )

    def test_card_update_edits_existing_zulip_message(self) -> None:
        self.assertTrue(
            self.bridge.update_card_message(
                project_id="project-1",
                message_id=1234,
                content="updated card",
                idempotency_key="zulip:outbound:update:1234:2",
                prev_content_sha256="abc",
            ),
        )
        self.assertEqual(self.zulip.updated, [(1234, "updated card", "abc")])

    def test_message_edit_appends_fact_but_ignores_rendering_only(self) -> None:
        self.assertTrue(
            self.bridge.handle_message_edit_event(
                ZulipMessageEditEvent(
                    event_id=300,
                    message_id=123,
                    user_id=5,
                    rendering_only=True,
                    content="preview update",
                    topic_name=None,
                ),
            ),
        )
        self.assertTrue(
            self.bridge.handle_message_edit_event(
                ZulipMessageEditEvent(
                    event_id=301,
                    message_id=123,
                    user_id=5,
                    rendering_only=False,
                    content="corrected claim",
                    topic_name="decisions",
                ),
            ),
        )
        events = self.ledger.list_events(limit=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "zulip_message_edited")


class SciforgeZulipSupportTests(TestCase):
    def test_event_normalizers_cover_webhook_queue_reaction_and_edit(self) -> None:
        webhook_event = message_event_from_outgoing_webhook(
            {
                "trigger": "mention",
                "message": {
                    "id": 10,
                    "stream_id": 7,
                    "display_recipient": "protein-design",
                    "topic": "hypothesis-1",
                    "sender_id": 5,
                    "sender_email": "user@example.com",
                    "content": "@**SciForge Agent** run",
                },
            },
        )
        self.assertEqual(webhook_event.trigger, "mention")
        self.assertEqual(webhook_event.stream_id, 7)

        queue_message = message_event_from_event_queue(
            {
                "id": 11,
                "type": "message",
                "message": {
                    "id": 12,
                    "type": "stream",
                    "stream_id": 7,
                    "display_recipient": "protein-design",
                    "subject": "hypothesis-1",
                    "sender_id": 5,
                    "sender_email": "user@example.com",
                    "content": "hello",
                },
            },
        )
        assert queue_message is not None
        self.assertEqual(queue_message.topic_name, "hypothesis-1")

        reaction = reaction_event_from_event_queue(
            {
                "id": 13,
                "type": "reaction",
                "message_id": 12,
                "user_id": 5,
                "emoji_name": "white_check_mark",
                "op": "add",
            },
        )
        assert reaction is not None
        self.assertEqual(reaction.emoji_name, "white_check_mark")

        edit = message_edit_event_from_event_queue(
            {
                "id": 14,
                "type": "update_message",
                "message_id": 12,
                "user_id": 5,
                "rendering_only": False,
                "content": "edited",
                "subject": "decisions",
            },
        )
        assert edit is not None
        self.assertEqual(edit.topic_name, "decisions")

    def test_cards_include_protocol_fields_and_unverified_markers(self) -> None:
        approval = ApprovalCard(
            header=CardHeader(
                card_type="approval",
                card_id="approval-1",
                idempotency_key="key-1",
            ),
            action="Publish draft",
            rationale="External visibility",
            risk="high",
            required_role="pi",
            evidence_refs=("ledger:e1",),
        )
        approval_markdown = render_approval_card(approval)
        self.assertIn("card_type=approval", approval_markdown)
        self.assertIn("`approve`", approval_markdown)
        self.assertIn("`ask_evidence`", approval_markdown)

        digest = WeeklyDigestCard(
            header=CardHeader(
                card_type="weekly_digest",
                card_id="digest-1",
                idempotency_key="key-2",
            ),
            project="protein-design",
            period_start="2026-06-22",
            period_end="2026-06-28",
            review_status="review_requested",
            progress=(DigestItem("Completed run", ("ledger:e2",)),),
            failed_runs=(),
            new_evidence=(DigestItem("Maybe improves binding", ("EDAG:C-4",), verified=False),),
            decisions=(),
            blocked=(),
            next_actions=(),
        )
        digest_markdown = render_weekly_digest_card(digest)
        self.assertIn("**unverified**", digest_markdown)
        self.assertIn("`EDAG:C-4`", digest_markdown)

    def test_ledger_is_append_only_and_tracks_delivery_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = ResearchLedger(Path(tmpdir) / "ledger.sqlite3")
            try:
                ledger.append_event(
                    LedgerEvent(
                        event_id="event-1",
                        project_id="project-1",
                        kind="redaction_recorded",
                        actor_kind="system",
                        payload={"message_id": 1},
                    ),
                )
                self.assertEqual(ledger.list_events()[0]["kind"], "redaction_recorded")
                self.assertEqual(ledger.health_summary()["ledger_events"], 1)
            finally:
                ledger.close()

    def test_redacted_config_does_not_print_secret_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "bot": {
                            "bot_api_key_env": "SCIFORGE_ZULIP_BOT_API_KEY",
                            "literal_token": "secret",
                        },
                        "runtime": {"token_env": "SCIFORGE_RUNTIME_TOKEN"},
                    },
                ),
            )
            redacted = load_redacted_config_dict(path)
            self.assertEqual(redacted["bot"]["bot_api_key_env"], "<redacted>")
            self.assertEqual(redacted["bot"]["literal_token"], "<redacted>")
            self.assertEqual(redacted["runtime"]["token_env"], "<redacted>")

    def test_digest_builder_preserves_source_refs_and_verified_state(self) -> None:
        draft = build_weekly_digest_draft(
            project_id="project-1",
            period_start="2026-06-22",
            period_end="2026-06-28",
            ledger_events=[
                {
                    "event_id": "ledger:e1",
                    "digest_section": "progress",
                    "summary": "Finished analysis",
                },
            ],
            evidence_claims=[
                {
                    "claim_id": "EDAG:C-1",
                    "summary": "Claim needs replication",
                    "verified": False,
                },
            ],
            paper_radar_items=[],
            runtime_summaries=[
                {
                    "thread_id": "thread-1",
                    "summary": "Needs PI answer",
                    "blocked": True,
                    "next_action": "Ask wet lab for RNA quality data",
                },
            ],
        )
        self.assertEqual(draft.progress[0].ref, "ledger:e1")
        self.assertFalse(draft.new_evidence[0].verified)
        self.assertEqual(draft.blocked[0].ref, "thread-1")
        self.assertEqual(draft.next_actions[0].summary, "Ask wet lab for RNA quality data")

    def test_collect_weekly_digest_draft_queries_all_sources(self) -> None:
        class EvidenceSource:
            def list_claims(
                self,
                *,
                project_id: str,
                period_start: str,
                period_end: str,
            ) -> list[dict[str, object]]:
                return [{"claim_id": "EDAG:C-1", "summary": "Evidence summary"}]

        class PaperSource:
            def list_digest_items(
                self,
                *,
                project_id: str,
                period_start: str,
                period_end: str,
            ) -> list[dict[str, object]]:
                return [{"paper_id": "paper:1", "summary": "Paper summary"}]

        class RuntimeSource:
            def list_thread_summaries(
                self,
                *,
                project_id: str,
                period_start: str,
                period_end: str,
            ) -> list[dict[str, object]]:
                return [{"thread_id": "thread-1", "next_action": "Review draft"}]

        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = ResearchLedger(Path(tmpdir) / "ledger.sqlite3")
            try:
                ledger.append_event(
                    LedgerEvent(
                        event_id="event-1",
                        project_id="project-1",
                        kind="decision_recorded",
                        actor_kind="zulip_user",
                        payload={"digest_section": "decisions", "summary": "PI approved"},
                        created_at="2026-06-25T00:00:00.000Z",
                    ),
                )
                draft = collect_weekly_digest_draft(
                    project_id="project-1",
                    period_start="2026-06-22",
                    period_end="2026-06-28",
                    ledger=ledger,
                    sources=WeeklyDigestSources(
                        evidence_dag=EvidenceSource(),
                        paper_radar=PaperSource(),
                        runtime=RuntimeSource(),
                    ),
                )
                self.assertEqual(draft.new_evidence[0].ref, "EDAG:C-1")
                self.assertEqual(draft.new_evidence[1].ref, "paper:1")
                self.assertEqual(draft.next_actions[0].ref, "thread-1")
            finally:
                ledger.close()
