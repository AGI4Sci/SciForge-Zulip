import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TOPICS: tuple[str, ...] = (
    "weekly-report",
    "agent-questions",
    "approvals",
    "decisions",
    "paper-radar",
    "failed-runs",
    "artifacts",
)

SENSITIVE_KEY_FRAGMENTS: tuple[str, ...] = ("api_key", "apikey", "token", "secret", "password")


@dataclass(frozen=True)
class ZulipBotConfig:
    realm_url: str
    bot_email: str
    bot_api_key_env: str
    bot_user_id: int | None = None

    def api_key(self) -> str:
        value = os.environ.get(self.bot_api_key_env, "")
        if not value:
            raise ValueError(f"Missing Zulip bot API key env var: {self.bot_api_key_env}")
        return value


@dataclass(frozen=True)
class StreamMapping:
    zulip_stream_id: int
    zulip_stream_name: str
    project_id: str
    workspace_root: str
    runtime_id: str = "sciforge"
    default_topics: tuple[str, ...] = DEFAULT_TOPICS


@dataclass(frozen=True)
class RuntimeConfig:
    base_url: str
    token_env: str
    default_governance_profile: str = "remote_guard"

    def token(self) -> str:
        value = os.environ.get(self.token_env, "")
        if not value:
            raise ValueError(f"Missing SciForge runtime token env var: {self.token_env}")
        return value


@dataclass(frozen=True)
class BridgeConfig:
    upstream_zulip_commit: str
    shallow_clone: bool
    require_full_history_before_release: bool
    ledger_path: str
    bot: ZulipBotConfig
    runtime: RuntimeConfig
    stream_mappings: tuple[StreamMapping, ...]

    def mapping_for_stream_id(self, stream_id: int) -> StreamMapping:
        for mapping in self.stream_mappings:
            if mapping.zulip_stream_id == stream_id:
                return mapping
        raise KeyError(f"No SciForge project mapping for Zulip stream id {stream_id}")


def _require_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or value == "":
        raise ValueError(f"Bridge config field {key!r} must be a non-empty string")
    return value


def _require_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise ValueError(f"Bridge config field {key!r} must be an integer")
    return value


def _load_stream_mapping(data: dict[str, Any]) -> StreamMapping:
    raw_topics = data.get("default_topics", DEFAULT_TOPICS)
    if not isinstance(raw_topics, list) or not all(isinstance(topic, str) for topic in raw_topics):
        raise ValueError("Bridge config field 'default_topics' must be a list of strings")
    return StreamMapping(
        zulip_stream_id=_require_int(data, "zulip_stream_id"),
        zulip_stream_name=_require_str(data, "zulip_stream_name"),
        project_id=_require_str(data, "project_id"),
        workspace_root=_require_str(data, "workspace_root"),
        runtime_id=str(data.get("runtime_id", "sciforge")),
        default_topics=tuple(raw_topics),
    )


def load_bridge_config(path: str | Path) -> BridgeConfig:
    raw_data = json.loads(Path(path).read_text())
    if not isinstance(raw_data, dict):
        raise ValueError("Bridge config root must be a JSON object")

    raw_bot = raw_data.get("bot")
    if not isinstance(raw_bot, dict):
        raise ValueError("Bridge config field 'bot' must be an object")

    raw_runtime = raw_data.get("runtime")
    if not isinstance(raw_runtime, dict):
        raise ValueError("Bridge config field 'runtime' must be an object")

    raw_mappings = raw_data.get("stream_mappings")
    if not isinstance(raw_mappings, list) or raw_mappings == []:
        raise ValueError("Bridge config field 'stream_mappings' must be a non-empty list")

    bot_user_id = raw_bot.get("bot_user_id")
    if bot_user_id is not None and not isinstance(bot_user_id, int):
        raise ValueError("Bridge config field 'bot.bot_user_id' must be an integer")

    return BridgeConfig(
        upstream_zulip_commit=_require_str(raw_data, "upstream_zulip_commit"),
        shallow_clone=bool(raw_data.get("shallow_clone", False)),
        require_full_history_before_release=bool(
            raw_data.get("require_full_history_before_release", True),
        ),
        ledger_path=_require_str(raw_data, "ledger_path"),
        bot=ZulipBotConfig(
            realm_url=_require_str(raw_bot, "realm_url").rstrip("/"),
            bot_email=_require_str(raw_bot, "bot_email"),
            bot_api_key_env=_require_str(raw_bot, "bot_api_key_env"),
            bot_user_id=bot_user_id,
        ),
        runtime=RuntimeConfig(
            base_url=_require_str(raw_runtime, "base_url").rstrip("/"),
            token_env=_require_str(raw_runtime, "token_env"),
            default_governance_profile=str(
                raw_runtime.get("default_governance_profile", "remote_guard"),
            ),
        ),
        stream_mappings=tuple(_load_stream_mapping(mapping) for mapping in raw_mappings),
    )


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, child_value in value.items():
            normalized_key = key.lower().replace("-", "_")
            if any(fragment in normalized_key for fragment in SENSITIVE_KEY_FRAGMENTS):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_secrets(child_value)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(child_value) for child_value in value]
    return value


def load_redacted_config_dict(path: str | Path) -> dict[str, Any]:
    raw_data = json.loads(Path(path).read_text())
    if not isinstance(raw_data, dict):
        raise ValueError("Bridge config root must be a JSON object")
    redacted = redact_secrets(raw_data)
    assert isinstance(redacted, dict)
    return redacted
