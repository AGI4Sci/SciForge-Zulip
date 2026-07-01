import base64
import json
from dataclasses import dataclass
from typing import Any
from urllib import parse, request


@dataclass(frozen=True)
class ZulipMessageTarget:
    stream: str
    topic: str


@dataclass(frozen=True)
class ZulipSendResult:
    message_id: int
    raw: dict[str, Any]


class ZulipRestClient:
    def __init__(self, *, realm_url: str, email: str, api_key: str) -> None:
        self.realm_url = realm_url.rstrip("/")
        self.email = email
        self.api_key = api_key

    def send_stream_message(self, target: ZulipMessageTarget, content: str) -> ZulipSendResult:
        data = parse.urlencode(
            {
                "type": "stream",
                "to": target.stream,
                "topic": target.topic,
                "content": content,
            },
        ).encode()
        raw = self._request_json("POST", "/api/v1/messages", data=data)
        message_id = raw.get("id")
        if not isinstance(message_id, int):
            raise RuntimeError(f"Zulip send response did not include integer id: {raw!r}")
        return ZulipSendResult(message_id=message_id, raw=raw)

    def update_message(
        self,
        message_id: int,
        content: str,
        *,
        prev_content_sha256: str | None = None,
    ) -> dict[str, Any]:
        payload = {"content": content}
        if prev_content_sha256 is not None:
            payload["prev_content_sha256"] = prev_content_sha256
        return self._request_json(
            "PATCH",
            f"/api/v1/messages/{message_id}",
            data=parse.urlencode(payload).encode(),
        )

    def test_auth(self) -> dict[str, Any]:
        return self._request_json("GET", "/api/v1/users/me")

    def _request_json(self, method: str, path: str, *, data: bytes | None = None) -> dict[str, Any]:
        req = request.Request(f"{self.realm_url}{path}", data=data, method=method)
        req.add_header("Authorization", _basic_auth(self.email, self.api_key))
        if data is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with request.urlopen(req, timeout=30) as response:
            body = response.read()
        raw = json.loads(body.decode())
        if not isinstance(raw, dict):
            raise RuntimeError(f"Zulip response must be a JSON object: {raw!r}")
        if raw.get("result") == "error":
            raise RuntimeError(str(raw.get("msg", "Zulip API error")))
        return raw


def _basic_auth(email: str, api_key: str) -> str:
    token = base64.b64encode(f"{email}:{api_key}".encode()).decode()
    return f"Basic {token}"
