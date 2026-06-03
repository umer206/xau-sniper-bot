from __future__ import annotations

import argparse
from dataclasses import replace

from .config import load_config
from .notifier import PushoverNotifier


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a test Pushover alert.")
    parser.add_argument("--config", default="config.json", help="Path to config JSON.")
    parser.add_argument("--title", default="XAU bot test", help="Notification title.")
    parser.add_argument(
        "--message",
        default="Pushover alerts are connected.",
        help="Notification body.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    config = replace(config, pushover_enabled=True)
    result = PushoverNotifier(config).send(args.title, args.message)
    print(f"sent={result.sent} status={result.status_code} message={result.message}")


if __name__ == "__main__":
    main()

