import argparse
import json
from pathlib import Path

from tools.sciforge_zulip_bridge.config import load_bridge_config, load_redacted_config_dict
from tools.sciforge_zulip_bridge.ledger import ResearchLedger
from tools.sciforge_zulip_bridge.zulip_client import ZulipMessageTarget, ZulipRestClient


def main() -> None:
    parser = argparse.ArgumentParser(description="SciForge Zulip Bridge helper")
    parser.add_argument("--config", required=True, help="Path to Bridge JSON config")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate-config")
    subparsers.add_parser("redacted-config")
    subparsers.add_parser("health")
    subparsers.add_parser("recent-failures")
    subparsers.add_parser("recent-deliveries")
    subparsers.add_parser("test-auth")
    send_test = subparsers.add_parser("send-test")
    send_test.add_argument("--stream", required=True)
    send_test.add_argument("--topic", required=True)
    send_test.add_argument("--content", required=True)

    args = parser.parse_args()
    config_path = Path(args.config)

    if args.command == "redacted-config":
        print(json.dumps(load_redacted_config_dict(config_path), ensure_ascii=False, indent=2))
        return

    config = load_bridge_config(config_path)
    if args.command == "validate-config":
        print("ok")
        return

    ledger = ResearchLedger(config.ledger_path)
    try:
        if args.command == "health":
            print(json.dumps(ledger.health_summary(), ensure_ascii=False, indent=2))
            return
        if args.command == "recent-failures":
            print(json.dumps(ledger.list_recent_failures(), ensure_ascii=False, indent=2))
            return
        if args.command == "recent-deliveries":
            print(json.dumps(ledger.list_deliveries(), ensure_ascii=False, indent=2))
            return

        zulip = ZulipRestClient(
            realm_url=config.bot.realm_url,
            email=config.bot.bot_email,
            api_key=config.bot.api_key(),
        )
        if args.command == "test-auth":
            raw = zulip.test_auth()
            print(json.dumps({"result": raw.get("result"), "email": raw.get("email")}, indent=2))
            return
        if args.command == "send-test":
            result = zulip.send_stream_message(
                ZulipMessageTarget(stream=args.stream, topic=args.topic),
                args.content,
            )
            print(json.dumps({"message_id": result.message_id}, indent=2))
            return
    finally:
        ledger.close()


if __name__ == "__main__":
    main()

