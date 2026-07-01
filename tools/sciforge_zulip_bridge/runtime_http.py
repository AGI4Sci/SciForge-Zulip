import json
from dataclasses import dataclass
from typing import Any
from urllib import request

from tools.sciforge_zulip_bridge.runtime import (
    AgentRuntimeClient,
    RuntimeThreadRequest,
    RuntimeTurnRequest,
    RuntimeTurnResult,
)


@dataclass(frozen=True)
class RuntimeHttpConfig:
    base_url: str
    token: str


class SciForgeRuntimeHttpClient(AgentRuntimeClient):
    """HTTP adapter for the SciForge local runtime `/v1/*` surface.

    This keeps the Bridge outside Zulip core.  When Bridge runs inside the
    SciForge desktop main process, the same protocol can be implemented by
    direct `AgentRuntimeHost` calls instead.
    """

    def __init__(self, config: RuntimeHttpConfig) -> None:
        self.base_url = config.base_url.rstrip("/")
        self.token = config.token

    def start_thread(self, request: RuntimeThreadRequest) -> str:
        raw = self._request_json(
            "POST",
            "/v1/threads",
            {
                "title": request.title,
                "workspace": request.workspace_root,
                "runtimeId": request.runtime_id,
                "metadata": request.metadata,
            },
        )
        thread_id = raw.get("id") or raw.get("threadId")
        if not isinstance(thread_id, str):
            raise RuntimeError(f"Runtime did not return a thread id: {raw!r}")
        return thread_id

    def start_turn(self, request: RuntimeTurnRequest) -> RuntimeTurnResult:
        thread_id = request.thread_id or self.start_thread(
            RuntimeThreadRequest(
                title=request.prompt.display_text[:80] or "Zulip task",
                workspace_root=request.workspace_root,
                runtime_id=request.runtime_id,
                metadata=request.metadata,
            ),
        )
        raw = self._request_json(
            "POST",
            f"/v1/threads/{thread_id}/turns",
            {
                "text": request.prompt.hidden_prompt,
                "displayText": request.prompt.display_text,
                "workspace": request.workspace_root,
                "runtimeId": request.runtime_id,
                "governanceProfile": request.governance_profile,
                "metadata": request.metadata,
            },
        )
        turn_id = raw.get("turnId") or raw.get("id")
        if not isinstance(turn_id, str):
            raise RuntimeError(f"Runtime did not return a turn id: {raw!r}")
        display_text = str(
            raw.get("displayText") or raw.get("summary") or "SciForge task accepted.",
        )
        return RuntimeTurnResult(
            thread_id=thread_id,
            turn_id=turn_id,
            display_text=display_text,
            status=str(raw.get("status", "running")),
            cards=tuple(raw.get("cards", ())) if isinstance(raw.get("cards", ()), list) else (),
        )

    def read_thread(self, thread_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/v1/threads/{thread_id}")

    def steer_turn(self, thread_id: str, turn_id: str, text: str, metadata: dict[str, Any]) -> None:
        self._request_json(
            "POST",
            f"/v1/threads/{thread_id}/turns/{turn_id}/steer",
            {"text": text, "metadata": metadata},
        )

    def resolve_approval(
        self,
        thread_id: str,
        approval_id: str,
        decision: str,
        metadata: dict[str, Any],
    ) -> None:
        self._request_json(
            "POST",
            f"/v1/approvals/{approval_id}",
            {
                "threadId": thread_id,
                "decision": _approval_decision_for_runtime(decision),
                "metadata": metadata,
            },
        )

    def resolve_user_input(
        self,
        thread_id: str,
        request_id: str,
        response: str,
        metadata: dict[str, Any],
    ) -> None:
        self._request_json(
            "POST",
            f"/v1/user-inputs/{request_id}",
            {"threadId": thread_id, "response": response, "metadata": metadata},
        )

    def _request_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        req = request.Request(f"{self.base_url}{path}", data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with request.urlopen(req, timeout=60) as response:
            raw_body = response.read()
        raw = json.loads(raw_body.decode()) if raw_body else {}
        if not isinstance(raw, dict):
            raise RuntimeError(f"Runtime response must be a JSON object: {raw!r}")
        return raw


def _approval_decision_for_runtime(decision: str) -> str:
    if decision == "approve":
        return "allow"
    if decision in {"reject", "request_changes", "ask_evidence"}:
        return "deny"
    raise ValueError(f"Unsupported approval decision: {decision}")
