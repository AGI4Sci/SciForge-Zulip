from typing import Any

from tools.sciforge_zulip_bridge.bridge import (
    ZulipMessageEditEvent,
    ZulipMessageEvent,
    ZulipReactionEvent,
)


def message_event_from_outgoing_webhook(payload: dict[str, Any]) -> ZulipMessageEvent:
    message = _require_dict(payload, "message")
    stream_id = int(message.get("stream_id") or message.get("stream_id_for_api") or 0)
    return ZulipMessageEvent(
        event_id=str(message.get("id") or payload.get("token") or payload.get("trigger")),
        message_id=_require_int(message, "id"),
        stream_id=stream_id,
        stream_name=str(message.get("display_recipient") or message.get("stream") or ""),
        topic_name=str(message.get("topic") or message.get("subject") or ""),
        sender_user_id=_require_int(message, "sender_id"),
        sender_email=str(message.get("sender_email") or ""),
        content=str(message.get("content") or payload.get("data") or ""),
        trigger=str(payload.get("trigger") or "outgoing_webhook"),
    )


def message_event_from_event_queue(event: dict[str, Any]) -> ZulipMessageEvent | None:
    if event.get("type") != "message":
        return None
    message = _require_dict(event, "message")
    if message.get("type") != "stream":
        return None
    display_recipient = message.get("display_recipient")
    stream_name = _stream_name_from_display_recipient(display_recipient)
    return ZulipMessageEvent(
        event_id=_require_event_id(event),
        message_id=_require_int(message, "id"),
        stream_id=_require_int(message, "stream_id"),
        stream_name=stream_name,
        topic_name=str(message.get("subject") or message.get("topic") or ""),
        sender_user_id=_require_int(message, "sender_id"),
        sender_email=str(message.get("sender_email") or ""),
        content=str(message.get("content") or ""),
        trigger="event_queue",
    )


def reaction_event_from_event_queue(event: dict[str, Any]) -> ZulipReactionEvent | None:
    if event.get("type") != "reaction":
        return None
    return ZulipReactionEvent(
        event_id=_require_event_id(event),
        message_id=_require_int(event, "message_id"),
        user_id=_require_int(event, "user_id"),
        emoji_name=str(event.get("emoji_name") or ""),
        op=str(event.get("op") or ""),
    )


def message_edit_event_from_event_queue(event: dict[str, Any]) -> ZulipMessageEditEvent | None:
    if event.get("type") != "update_message":
        return None
    return ZulipMessageEditEvent(
        event_id=_require_event_id(event),
        message_id=_require_int(event, "message_id"),
        user_id=int(event["user_id"]) if event.get("user_id") is not None else None,
        rendering_only=event.get("rendering_only") is True,
        content=str(event["content"]) if event.get("content") is not None else None,
        topic_name=str(event["subject"]) if event.get("subject") is not None else None,
    )


def normalize_event_queue_event(
    event: dict[str, Any],
) -> ZulipMessageEvent | ZulipReactionEvent | ZulipMessageEditEvent | None:
    return (
        message_event_from_event_queue(event)
        or reaction_event_from_event_queue(event)
        or message_edit_event_from_event_queue(event)
    )


def _stream_name_from_display_recipient(display_recipient: object) -> str:
    if isinstance(display_recipient, str):
        return display_recipient
    if isinstance(display_recipient, list) and display_recipient:
        first = display_recipient[0]
        if isinstance(first, dict):
            name = first.get("name")
            if isinstance(name, str):
                return name
    return ""


def _require_dict(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Expected {key} to be an object")
    return value


def _require_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise ValueError(f"Expected {key} to be an integer")
    return value


def _require_event_id(event: dict[str, Any]) -> int | str:
    event_id = event.get("id")
    if not isinstance(event_id, int | str):
        raise ValueError("Expected event id")
    return event_id

