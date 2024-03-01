import argparse
import logging
import random
import sys
from pathlib import Path

from slack_scheduler.auth import TokenExpiredError, TokenInvalidError
from slack_scheduler.logger import setup_logging
from slack_scheduler.sender import SlackAPIError

log = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        prog="slack-scheduler",
        description="Schedule and send Slack messages using browser session tokens.",
    )

    # Global flags
    parser.add_argument(
        "--config", type=Path, default=Path("config.yaml"),
        help="Path to config.yaml (default: ./config.yaml)",
    )
    parser.add_argument(
        "--env", type=Path, default=Path(".env"),
        help="Path to .env file with credentials (default: ./.env)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview actions without sending anything",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable debug-level log output",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # send
    send_parser = subparsers.add_parser(
        "send", help="Send a message immediately",
    )
    send_parser.add_argument(
        "--channel", type=str, required=True,
        help="Target channel ID",
    )
    send_parser.add_argument(
        "--message", type=str, nargs="+",
        help="Message text (multiple for random selection)",
    )
    send_parser.add_argument(
        "--workspace", type=str,
        help="Workspace URL (overrides config)",
    )

    # run
    subparsers.add_parser(
        "run", help="Start the daemon scheduler",
    )

    # status
    status_parser = subparsers.add_parser(
        "status", help="Show upcoming scheduled messages",
    )
    status_parser.add_argument(
        "--count", type=int, default=5,
        help="Number of upcoming events to show per schedule (default: 5)",
    )

    # validate
    subparsers.add_parser(
        "validate", help="Check that stored credentials are valid",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    setup_logging(verbose=args.verbose)

    try:
        if args.command == "send":
            cmd_send(args)
        elif args.command == "run":
            cmd_run(args)
        elif args.command == "status":
            cmd_status(args)
        elif args.command == "validate":
            cmd_validate(args)
    except TokenExpiredError as e:
        log.error(str(e))
        sys.exit(1)
    except TokenInvalidError as e:
        log.error(str(e))
        sys.exit(1)
    except SlackAPIError as e:
        log.error(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        log.info("Interrupted. Exiting.")
        sys.exit(0)
    except FileNotFoundError as e:
        log.error(str(e))
        sys.exit(1)
    except ValueError as e:
        log.error(str(e))
        sys.exit(1)
    except Exception as e:
        log.exception(f"Unexpected error: {e}")
        sys.exit(1)


def cmd_send(args):
    from slack_scheduler.auth import validate_credentials
    from slack_scheduler.config import load_config, load_credentials
    from slack_scheduler.sender import send_message
    from slack_scheduler.templates import render
    from datetime import datetime

    credentials = load_credentials(args.env)

    # Resolve workspace URL: CLI flag > config > error
    workspace_url = args.workspace
    if not workspace_url and args.config.exists():
        config = load_config(args.config)
        workspace_url = config.workspace_url
    if not workspace_url:
        log.error("Workspace URL required. Use --workspace or set it in config.yaml.")
        sys.exit(1)

    validate_credentials(credentials, workspace_url)

    # Resolve message: CLI flag > config channel messages > error
    if args.message:
        message = random.choice(args.message)
    elif args.config.exists():
        config = load_config(args.config)
        channel_cfg = next((c for c in config.channels if c.id == args.channel), None)
        if channel_cfg and channel_cfg.messages:
            from slack_scheduler.selector import pick_message
            message = pick_message(
                args.channel, channel_cfg.messages, channel_cfg.selection_mode,
            )
        else:
            log.error("No --message provided and no messages in config for this channel.")
            sys.exit(1)
    else:
        log.error("No --message provided and no config file found.")
        sys.exit(1)

    message = render(message, datetime.now())

    result = send_message(
        channel_id=args.channel,
        message=message,
        credentials=credentials,
        workspace_url=workspace_url,
        dry_run=args.dry_run,
    )

    if result.ok:
        print(f"Message sent: {message!r}")
    else:
        log.error(f"Failed to send: {result.error_code}")
        sys.exit(1)


def cmd_run(args):
    from slack_scheduler.auth import validate_credentials
    from slack_scheduler.config import load_config, load_credentials
    from slack_scheduler.scheduler import run_daemon

    config = load_config(args.config)
    credentials = load_credentials(args.env)
    validate_credentials(credentials, config.workspace_url)

    run_daemon(config, credentials, dry_run=args.dry_run)


def cmd_status(args):
    from slack_scheduler.config import load_config
    from slack_scheduler.scheduler import print_upcoming

    config = load_config(args.config)
    print_upcoming(config, count=args.count)


def cmd_validate(args):
    from slack_scheduler.auth import validate_credentials
    from slack_scheduler.config import load_config, load_credentials

    credentials = load_credentials(args.env)

    workspace_url = None
    if args.config.exists():
        config = load_config(args.config)
        workspace_url = config.workspace_url

    if not workspace_url:
        log.error("Workspace URL required. Set it in config.yaml.")
        sys.exit(1)

    validate_credentials(credentials, workspace_url)
    print("Credentials are valid.")


if __name__ == "__main__":
    main()
